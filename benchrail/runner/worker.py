"""Worker: full lifecycle of one task (instance_id + agent_config)."""

from __future__ import annotations

import os
import shlex
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from benchrail.adapters.base import AgentRunResult
from benchrail.dto.config import InstanceConfig
from benchrail.dto.manifest import AgentEntry
from benchrail.dto.result import AgentStats, CheckResult, InstanceResult
from benchrail.registry import build_adapter
from benchrail.runner.logging_util import ConsoleOutput, RunnerLogger


@dataclass
class TaskSpec:
    instance_id: str
    agent_entry: AgentEntry
    instance_config: InstanceConfig
    instance_dir: Path
    workspace_root: Path
    output_root: Path | None
    logs_root: Path
    run_id: str
    mode: str
    auth_session: bool
    stop_flag: threading.Event


class _StepFailed(Exception):
    def __init__(self, reason: str, step: str, exit_code: int = -1):
        super().__init__(reason)
        self.reason = reason
        self.step = step
        self.exit_code = exit_code


class _ConsoleLike(Protocol):
    def print(self, msg: str) -> None: ...


def _resolve_local_env() -> dict[str, str]:
    """In local mode inherit the full process environment."""
    return dict(os.environ)


def _resolve_docker_env(spec: TaskSpec) -> dict[str, str]:
    """Build Docker runtime env from instance config and agent manifest."""
    docker_config = spec.instance_config.docker
    inherited_env, missing = _resolve_env_from_host(
        spec.agent_entry.agent,
        docker_config.env_from_host,
    )
    if missing:
        raise _StepFailed(
            reason=f"missing docker env vars: {', '.join(sorted(missing))}",
            step="env_resolution",
        )

    result = dict(docker_config.env)
    result.update(inherited_env)
    _apply_codex_exec_auth_env(spec.agent_entry.agent, result)
    result.update(_agent_runtime_env(spec.agent_entry, result))
    return result


def _resolve_env_from_host(
    agent_name: str,
    requested_names: list[str],
) -> tuple[dict[str, str], list[str]]:
    result: dict[str, str] = {}
    missing: list[str] = []
    alias_map: dict[str, tuple[str, ...]] = {}
    if agent_name == "codex":
        alias_map = {
            "OPENAI_API_KEY": ("CODEX_API_KEY",),
            "CODEX_API_KEY": ("OPENAI_API_KEY",),
        }

    for name in requested_names:
        if name in os.environ:
            result[name] = os.environ[name]
            continue
        aliases = alias_map.get(name, ())
        matched = False
        for alias in aliases:
            if alias in os.environ:
                result[name] = os.environ[alias]
                matched = True
                break
        if not matched:
            missing.append(name)
    return result, missing


def _apply_codex_exec_auth_env(agent_name: str, env: dict[str, str]) -> None:
    if agent_name != "codex":
        return
    if env.get("CODEX_API_KEY"):
        return
    api_key = env.get("OPENAI_API_KEY")
    if api_key:
        env["CODEX_API_KEY"] = api_key


def _copy_auth_session_file_if_needed(
    spec: TaskSpec,
    adapter: Any,
    docker_runner: Any,
    docker_module: Any,
) -> None:
    if not spec.auth_session:
        return
    session_file = adapter.auth_session_file()
    if session_file is None:
        return
    if not session_file.exists():
        raise _StepFailed(
            reason=f"agent auth subscription file not found: {session_file}",
            step="docker_start",
        )

    home_dir = Path.home()
    try:
        relpath = session_file.relative_to(home_dir)
    except ValueError as exc:
        raise _StepFailed(
            reason=(f"agent auth subscription file must be under home directory: {session_file}"),
            step="docker_start",
        ) from exc

    try:
        docker_module.copy_file_to_container(
            docker_runner,
            session_file,
            "/root",
            str(relpath),
        )
    except Exception as exc:
        raise _StepFailed(
            f"failed to copy agent auth subscription: {exc}",
            "docker_start",
        ) from exc


def _agent_runtime_env(agent_entry: AgentEntry, existing_env: dict[str, str]) -> dict[str, str]:
    """Map manifest agent/version to runtime env vars for universal images."""
    runtime_var_by_agent = {
        "codex": "BENCH_ENV_CODEX_VERSION",
        "claude-code": "BENCH_ENV_CLAUDE_CODE_VERSION",
    }
    env_name = runtime_var_by_agent.get(agent_entry.agent)
    if env_name is None or env_name in existing_env:
        return {}
    version = agent_entry.version or "latest"
    return {env_name: version}


def _bench_env_vars(
    spec: TaskSpec,
    task_dir: Path,
    repo_dir: Path,
    bench_env_dir: Path,
    mode: str,
) -> dict[str, str]:
    if mode == "docker":
        bench_repo = "/bench/repo"
        bench_env = "/bench/environment"
    else:
        bench_repo = str(repo_dir)
        bench_env = str(bench_env_dir)

    return {
        "BENCH_ENV_RUN_ID": spec.run_id,
        "BENCH_ENV_AGENT_ID": spec.agent_entry.id,
        "BENCH_ENV_AGENT": spec.agent_entry.agent,
        "BENCH_ENV_INSTANCE_ID": spec.instance_id,
        "BENCH_ENV_MODE": mode,
        "BENCH_ENV_WORKSPACE": str(spec.workspace_root),
        "BENCH_ENV_REPO_DIR": bench_repo,
        "BENCH_ENV_DIR": bench_env,
    }


def _resolve_dockerfile(spec: TaskSpec) -> Path | None:
    try:
        return spec.instance_config.docker.resolve_dockerfile_path(
            spec.instance_dir,
            spec.instance_dir.parent,
        )
    except ValueError as exc:
        raise _StepFailed(str(exc), "docker_build") from exc


def _build_agent_stats(agent_run: AgentRunResult | None) -> AgentStats:
    if agent_run is None:
        return AgentStats()
    return AgentStats(
        duration_ms=agent_run.duration_ms,
        turns=agent_run.turns,
        input_tokens=agent_run.input_tokens,
        output_tokens=agent_run.output_tokens,
        cache_read_tokens=agent_run.cache_read_tokens,
        cache_creation_tokens=agent_run.cache_creation_tokens,
        reasoning_tokens=agent_run.reasoning_tokens,
        cost_usd=agent_run.cost_usd,
        cost_credits=agent_run.cost_credits,
    )


def _write_result_atomic(result: InstanceResult, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(result.model_dump_json(indent=2), encoding="utf-8")
    tmp.rename(path)


def _result_path(spec: TaskSpec) -> Path:
    base = spec.output_root or spec.workspace_root
    return base / spec.run_id / spec.agent_entry.id / spec.instance_id / "result.json"


def _agent_patch_path(spec: TaskSpec) -> Path:
    return _result_path(spec).with_name("agent.patch")


def _task_workspace_dir(spec: TaskSpec) -> Path:
    return spec.workspace_root / spec.run_id / spec.agent_entry.id / spec.instance_id


def _task_logs_dir(spec: TaskSpec) -> Path:
    return spec.logs_root / spec.run_id / spec.agent_entry.id / spec.instance_id


def _emit_task_runner_log(spec: TaskSpec, console: _ConsoleLike) -> None:
    log_path = _task_logs_dir(spec) / "runner.log"
    header = (
        f"--- RUNNER_LOG instance={spec.instance_id} agent={spec.agent_entry.id}"
        f" path={log_path} ---"
    )
    footer = f"--- END_RUNNER_LOG instance={spec.instance_id} agent={spec.agent_entry.id} ---"
    if not log_path.exists():
        console.print(f"\n{header}\n[missing runner.log]\n{footer}")
        return
    log_text = log_path.read_text(encoding="utf-8", errors="replace").rstrip()
    body = log_text if log_text else "[empty runner.log]"
    console.print(f"\n{header}\n{body}\n{footer}")


def _log_agent_invocation(
    task_logger: RunnerLogger,
    agent_cmd: list[str],
    prompt: str,
    env: dict[str, str],
) -> None:
    task_logger.debug("AGENT_CMD", command=shlex.join(agent_cmd))
    task_logger.debug("AGENT_PROMPT", prompt=prompt)
    task_logger.debug("AGENT_ENV_VARS", names=" ".join(sorted(env.keys())))


def _agent_patch_script() -> str:
    return """
set -eu
git diff --binary --no-ext-diff -- .
git ls-files --others --exclude-standard | while IFS= read -r path; do
  [ -n "$path" ] || continue
  git diff --binary --no-index -- /dev/null "$path" || true
done
""".strip()


def _snapshot_agent_patch_local(
    spec: TaskSpec,
    repo_dir: Path,
    env: dict[str, str],
    logs_dir: Path,
    task_logger: RunnerLogger,
) -> None:
    patch_path = _agent_patch_path(spec)
    patch_path.parent.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(
        _agent_patch_script(),
        cwd=repo_dir,
        env=env,
        shell=True,
        check=False,
        capture_output=True,
        text=True,
    )
    patch_path.write_text(r.stdout, encoding="utf-8")
    if r.returncode != 0:
        task_logger.warn(
            "AGENT_PATCH_SNAPSHOT_FAILED",
            path=str(patch_path),
            exit_code=r.returncode,
            stderr_tail=r.stderr[-500:].strip(),
        )
        return
    task_logger.info(
        "AGENT_PATCH_SNAPSHOT_END",
        path=str(patch_path),
        bytes=patch_path.stat().st_size,
    )


def _snapshot_agent_patch_docker(
    spec: TaskSpec,
    docker_runner: Any,
    env: dict[str, str],
    logs_dir: Path,
    task_logger: RunnerLogger,
) -> None:
    patch_path = _agent_patch_path(spec)
    patch_path.parent.mkdir(parents=True, exist_ok=True)
    r = docker_runner.exec(
        ["sh", "-c", _agent_patch_script()],
        workdir="/bench/repo",
        env=env,
        timeout=120,
        stdout_path=patch_path,
        stderr_path=logs_dir / "agent_patch.stderr",
        event_name="AGENT_PATCH_SNAPSHOT",
    )
    if r.exit_code != 0 or r.timed_out:
        task_logger.warn(
            "AGENT_PATCH_SNAPSHOT_FAILED",
            path=str(patch_path),
            exit_code=r.exit_code,
            timed_out=r.timed_out,
            stderr_tail=r.stderr_tail,
        )
        return
    task_logger.info(
        "AGENT_PATCH_SNAPSHOT_END",
        path=str(patch_path),
        bytes=patch_path.stat().st_size if patch_path.exists() else 0,
    )


def _warn_if_agent_succeeded_without_changes(
    task_logger: RunnerLogger,
    agent_run: AgentRunResult | None,
    patch_path: Path,
    modified_files: list[str],
) -> None:
    if agent_run is None or agent_run.exit_code != 0:
        return
    patch_bytes = patch_path.stat().st_size if patch_path.exists() else 0
    if patch_bytes > 0 or modified_files:
        return
    task_logger.warn(
        "AGENT_NO_CHANGES",
        path=str(patch_path),
        bytes=patch_bytes,
        modified_files_count=0,
        note="agent finished successfully but left no repository changes",
    )


def _parse_patch_touched_files(patch_path: Path) -> list[str]:
    files: list[str] = []
    seen: set[str] = set()
    for line in patch_path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.startswith("diff --git "):
            continue
        parts = line.split()
        if len(parts) < 4:
            continue
        candidate = parts[2]
        if candidate.startswith("a/"):
            candidate = candidate[2:]
        if candidate != "/dev/null" and candidate not in seen:
            seen.add(candidate)
            files.append(candidate)
    return files


def _sample_items(items: list[str], limit: int = 8) -> str:
    if len(items) <= limit:
        return ",".join(items)
    shown = ",".join(items[:limit])
    return f"{shown},...(+{len(items) - limit} more)"


def _modified_files_local(repo_dir: Path, env: dict[str, str]) -> list[str]:
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=repo_dir,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return []
    files: list[str] = []
    seen: set[str] = set()
    for line in result.stdout.splitlines():
        if len(line) < 4:
            continue
        path = line[3:]
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        if path not in seen:
            seen.add(path)
            files.append(path)
    return files


def _modified_files_docker(
    docker_runner: Any,
    env: dict[str, str],
    logs_dir: Path,
) -> list[str]:
    status_stdout = logs_dir / "agent_modified_files.stdout"
    status_stderr = logs_dir / "agent_modified_files.stderr"
    result = docker_runner.exec(
        ["git", "status", "--porcelain"],
        workdir="/bench/repo",
        env=env,
        timeout=30,
        stdout_path=status_stdout,
        stderr_path=status_stderr,
        event_name="AGENT_MODIFIED_FILES",
    )
    if result.exit_code != 0 or result.timed_out:
        return []
    files: list[str] = []
    seen: set[str] = set()
    for line in status_stdout.read_text(encoding="utf-8", errors="replace").splitlines():
        if len(line) < 4:
            continue
        path = line[3:]
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        if path not in seen:
            seen.add(path)
            files.append(path)
    return files


def _log_patch_context(
    patch_path: Path,
    modified_files: list[str],
    task_logger: RunnerLogger,
    log_prefix: str,
) -> None:
    patch_files = _parse_patch_touched_files(patch_path)
    overlap = sorted(set(patch_files) & set(modified_files))
    event_prefix = log_prefix.upper()
    task_logger.info(
        f"{event_prefix}_CONTEXT",
        path=str(patch_path),
        touched_files_count=len(patch_files),
        touched_files_sample=_sample_items(patch_files),
        modified_files_count=len(modified_files),
        modified_files_sample=_sample_items(modified_files),
        note="patch compatibility still depends on dataset design and post-agent repository state",
    )
    if overlap:
        task_logger.warn(
            f"{event_prefix}_OVERLAP",
            overlap_count=len(overlap),
            overlap_sample=_sample_items(overlap),
            hint="patch touches files already modified by the agent; conflict risk is elevated",
        )


# ─── Local mode ────────────────────────────────────────────────────────────────


def _run_local(
    spec: TaskSpec,
    run_logger: RunnerLogger,
    console: ConsoleOutput,
) -> InstanceResult:
    from benchrail.runner import local as loc

    task_dir = _task_workspace_dir(spec)
    task_logs_dir = _task_logs_dir(spec)
    logs_dir = task_logs_dir / "logs"
    bench_env_dir = task_dir / "environment"
    repo_dir = task_dir / "repo"

    task_logger = RunnerLogger(task_logs_dir / "runner.log")
    task_logger.info("TASK_START", instance=spec.instance_id, agent=spec.agent_entry.id)
    console.task_start(spec.instance_id, spec.agent_entry.id)
    start_time = time.monotonic()

    checks: list[CheckResult] = []
    agent_run: AgentRunResult | None = None
    fail_step: str | None = None
    fail_exit_code: int | None = None

    timeout_event = threading.Event()
    timer: threading.Timer | None = None
    if spec.instance_config.instance_timeout_sec:
        timer = threading.Timer(spec.instance_config.instance_timeout_sec, timeout_event.set)
        timer.daemon = True
        timer.start()

    def _check_timeout() -> None:
        if timeout_event.is_set():
            elapsed = int((time.monotonic() - start_time) * 1000)
            task_logger.warn(
                "INSTANCE_TIMEOUT",
                elapsed_ms=elapsed,
                limit_ms=(spec.instance_config.instance_timeout_sec or 0) * 1000,
            )
            raise _StepFailed("instance_timeout", "timeout")

    def _check_stop() -> None:
        if spec.stop_flag.is_set():
            raise _StepFailed("aborted", "abort")

    try:
        task_dir.mkdir(parents=True, exist_ok=True)
        task_logs_dir.mkdir(parents=True, exist_ok=True)
        logs_dir.mkdir(exist_ok=True)
        bench_env_dir.mkdir(exist_ok=True)

        env = _resolve_local_env()
        env.update(_bench_env_vars(spec, task_dir, repo_dir, bench_env_dir, "local"))

        # Copy dataset environment first, then overlay instance-specific files.
        loc.copy_environment_layers(
            [
                spec.instance_dir.parent / "environment",
                spec.instance_dir / "environment",
            ],
            bench_env_dir,
        )

        _check_stop()
        _check_timeout()

        # Clone & setup repository
        err = loc.setup_repository(
            repo_url=spec.instance_config.repo,
            base_commit=spec.instance_config.base_commit,
            repo_dir=repo_dir,
            parent_dir=task_dir,
            env=env,
            logs_dir=logs_dir,
            logger=task_logger,
        )
        if err:
            raise _StepFailed(err, "clone", exit_code=1)

        _check_stop()
        _check_timeout()

        # Apply prepare_patch
        prepare_path, test_path = spec.instance_config.resolve_patch_paths(spec.instance_dir)
        if prepare_path:
            r = loc.apply_patch(prepare_path, repo_dir, env, logs_dir, "prepare_patch", task_logger)
            if r.exit_code != 0:
                raise _StepFailed("prepare_patch failed", "prepare_patch", r.exit_code)

        _check_stop()
        _check_timeout()

        # before_agent hook
        hooks = spec.instance_config.hooks
        if hooks and hooks.before_agent:
            hook = hooks.before_agent
            r = loc.run_command(
                hook.command,
                cwd=repo_dir,
                env=env,
                timeout=hook.timeout_sec,
                stdout_path=logs_dir / "before_agent.stdout",
                stderr_path=logs_dir / "before_agent.stderr",
                logger=task_logger,
                event_name="BEFORE_AGENT",
                shell=True,
                log_extra={"command": hook.command},
            )
            if r.exit_code != 0 or r.timed_out:
                raise _StepFailed("before_agent hook failed", "before_agent", r.exit_code)

        _check_stop()
        _check_timeout()

        # Run agent
        adapter = build_adapter(
            spec.agent_entry.agent,
            spec.agent_entry.command,
            [],
        )
        agent_cmd = adapter.build_command(spec.instance_config.prompt, execution_mode="local")
        agent_timeout = spec.instance_config.instance_timeout_sec or 7200

        _log_agent_invocation(task_logger, agent_cmd, spec.instance_config.prompt, env)

        agent_result = loc.run_command(
            agent_cmd,
            cwd=repo_dir,
            env=env,
            timeout=agent_timeout,
            stdout_path=logs_dir / "agent.stdout",
            stderr_path=logs_dir / "agent.stderr",
            logger=task_logger,
            event_name="AGENT",
            shell=False,
            log_extra={"agent": spec.agent_entry.agent},
        )

        stdout_data = (logs_dir / "agent.stdout").read_bytes()
        stderr_data = (logs_dir / "agent.stderr").read_bytes()
        agent_run = adapter.parse_result(
            stdout_data, stderr_data, agent_result.exit_code, agent_result.duration_ms
        )

        task_logger.info(
            "AGENT_END",
            duration_ms=agent_run.duration_ms,
            exit_code=agent_result.exit_code,
            turns=agent_run.turns,
            input_tokens=agent_run.input_tokens,
            output_tokens=agent_run.output_tokens,
            cache_read_tokens=agent_run.cache_read_tokens,
            cost_usd=agent_run.cost_usd,
            cost_credits=agent_run.cost_credits,
        )
        _snapshot_agent_patch_local(spec, repo_dir, env, logs_dir, task_logger)
        modified_files = _modified_files_local(repo_dir, env)
        _warn_if_agent_succeeded_without_changes(
            task_logger,
            agent_run,
            _agent_patch_path(spec),
            modified_files,
        )

        # Apply test_patch (even if agent failed)
        if test_path:
            _log_patch_context(
                test_path,
                modified_files,
                task_logger,
                "test_patch",
            )
            r = loc.apply_patch(test_path, repo_dir, env, logs_dir, "test_patch", task_logger)
            if r.exit_code != 0:
                raise _StepFailed("test_patch failed", "test_patch", r.exit_code)

        _check_stop()
        _check_timeout()

        # before_checks hook
        if hooks and hooks.before_checks:
            hook = hooks.before_checks
            r = loc.run_command(
                hook.command,
                cwd=repo_dir,
                env=env,
                timeout=hook.timeout_sec,
                stdout_path=logs_dir / "before_checks.stdout",
                stderr_path=logs_dir / "before_checks.stderr",
                logger=task_logger,
                event_name="BEFORE_CHECKS",
                shell=True,
                log_extra={"command": hook.command},
            )
            if r.exit_code != 0 or r.timed_out:
                raise _StepFailed("before_checks hook failed", "before_checks", r.exit_code)

        # Run checks (run all, don't stop on first failure)
        for check in spec.instance_config.check_commands:
            _check_stop()
            _check_timeout()

            task_logger.info("CHECK_START", name=check.name, command=check.command)
            check_start = time.monotonic()

            r = loc.run_command(
                check.command,
                cwd=repo_dir,
                env=env,
                timeout=check.timeout_sec,
                stdout_path=logs_dir / f"check_{check.name}.stdout",
                stderr_path=logs_dir / f"check_{check.name}.stderr",
                logger=task_logger,
                event_name=f"CHECK_{check.name.upper()}",
                shell=True,
            )
            check_dur = time.monotonic() - check_start

            if r.timed_out:
                status = "error"
            elif r.exit_code == 0:
                status = "pass"
            else:
                status = "fail"

            checks.append(
                CheckResult(
                    name=check.name,
                    status=status,
                    exit_code=r.exit_code,
                    duration_seconds=round(check_dur, 3),
                )
            )
            task_logger.info(
                "CHECK_END",
                name=check.name,
                status=status,
                duration_ms=r.duration_ms,
                exit_code=r.exit_code,
            )

    except _StepFailed as exc:
        fail_step = exc.step
        fail_exit_code = exc.exit_code
        task_logger.error("TASK_FAIL", reason=exc.reason, step=exc.step)
    except Exception as exc:
        fail_step = "unexpected"
        fail_exit_code = -1
        task_logger.error("TASK_FAIL", reason=str(exc)[:500], step="unexpected")
    finally:
        if timer:
            timer.cancel()

    duration_seconds = round(time.monotonic() - start_time, 1)
    instance_status = (
        "pass"
        if checks and all(c.status == "pass" for c in checks) and fail_step is None
        else "fail"
    )

    result = InstanceResult(
        instance_id=spec.instance_id,
        agent=spec.agent_entry.id,
        agent_session_id=(agent_run.agent_session_id if agent_run else ""),
        repo=spec.instance_config.repo,
        base_commit=spec.instance_config.base_commit,
        status=instance_status,
        duration_seconds=duration_seconds,
        agent_stats=_build_agent_stats(agent_run),
        checks=checks,
    )

    _write_result_atomic(result, _result_path(spec))

    task_logger.info("TASK_END", status=instance_status, duration_seconds=duration_seconds)
    console.task_end(
        instance=spec.instance_id,
        agent=spec.agent_entry.id,
        status=instance_status,
        duration=duration_seconds,
        turns=agent_run.turns if agent_run else None,
        input_tokens=agent_run.input_tokens if agent_run else None,
        cost_usd=agent_run.cost_usd if agent_run else None,
        cost_credits=agent_run.cost_credits if agent_run else None,
        fail_step=fail_step,
        fail_exit_code=fail_exit_code,
    )
    task_logger.close()
    _emit_task_runner_log(spec, console)
    return result


# ─── Docker mode ───────────────────────────────────────────────────────────────


def _run_docker(
    spec: TaskSpec,
    run_logger: RunnerLogger,
    console: ConsoleOutput,
) -> InstanceResult:
    from benchrail.runner import docker as dk

    task_dir = _task_workspace_dir(spec)
    task_logs_dir = _task_logs_dir(spec)
    logs_dir = task_logs_dir / "logs"
    bench_env_dir = task_dir / "environment"

    task_logger = RunnerLogger(task_logs_dir / "runner.log")
    task_logger.info("TASK_START", instance=spec.instance_id, agent=spec.agent_entry.id)
    console.task_start(spec.instance_id, spec.agent_entry.id)
    start_time = time.monotonic()

    checks: list[CheckResult] = []
    agent_run: AgentRunResult | None = None
    fail_step: str | None = None
    fail_exit_code: int | None = None
    docker_runner: dk.DockerTaskRunner | None = None

    timeout_event = threading.Event()
    timer: threading.Timer | None = None
    if spec.instance_config.instance_timeout_sec:
        timer = threading.Timer(spec.instance_config.instance_timeout_sec, timeout_event.set)
        timer.daemon = True
        timer.start()

    def _check_timeout() -> None:
        if timeout_event.is_set():
            elapsed = int((time.monotonic() - start_time) * 1000)
            task_logger.warn(
                "INSTANCE_TIMEOUT",
                elapsed_ms=elapsed,
                limit_ms=(spec.instance_config.instance_timeout_sec or 0) * 1000,
            )
            raise _StepFailed("instance_timeout", "timeout")

    def _check_stop() -> None:
        if spec.stop_flag.is_set():
            raise _StepFailed("aborted", "abort")

    try:
        task_dir.mkdir(parents=True, exist_ok=True)
        task_logs_dir.mkdir(parents=True, exist_ok=True)
        logs_dir.mkdir(exist_ok=True)
        bench_env_dir.mkdir(exist_ok=True)

        env: dict[str, str] = {}
        docker_env = _resolve_docker_env(spec)
        env.update(_bench_env_vars(spec, task_dir, Path("/bench/repo"), bench_env_dir, "docker"))
        env.update(docker_env)

        # Copy dataset environment first, then overlay instance-specific files.
        from benchrail.runner.local import copy_environment_layers

        copy_environment_layers(
            [
                spec.instance_dir.parent / "environment",
                spec.instance_dir / "environment",
            ],
            bench_env_dir,
        )

        _check_stop()

        docker_config = spec.instance_config.docker
        if docker_config.image:
            image_ref = docker_config.image
        else:
            dockerfile = _resolve_dockerfile(spec)
            if dockerfile is None:
                raise _StepFailed(
                    "docker config must define either docker.image or docker.dockerfile",
                    "docker_build",
                )
            image_ref = dk.make_image_tag(spec.run_id, spec.agent_entry.id, spec.instance_id)
            success = dk.build_image(
                dockerfile.parent,
                dockerfile.name,
                image_ref,
                logs_dir,
                task_logger,
            )
            if not success:
                raise _StepFailed("docker build failed", "docker_build")

        _check_stop()
        _check_timeout()

        # Determine patches dir
        patches_src = spec.instance_dir / "patches"
        docker_runner = dk.create_task_runner(
            image_ref,
            bench_env_dir,
            patches_src if patches_src.exists() else None,
            docker_env,
            task_logger,
        )
        if docker_runner is None:
            raise _StepFailed("container create/start failed", "docker_start")

        # Clone inside container
        r = docker_runner.exec(
            ["git", "clone", spec.instance_config.repo, "/bench/repo"],
            workdir="/",
            env=env,
            timeout=600,
            stdout_path=logs_dir / "clone.stdout",
            stderr_path=logs_dir / "clone.stderr",
            event_name="CLONE",
            log_extra={"repo": spec.instance_config.repo},
        )
        if r.exit_code != 0 or r.timed_out:
            raise _StepFailed("clone failed", "clone", r.exit_code)

        # Git cleanup inside container
        cleanup_cmds = [
            ["git", "reset", "--hard", spec.instance_config.base_commit],
            ["git", "remote", "remove", "origin"],
            ["git", "reflog", "expire", "--expire=now", "--all"],
            ["git", "gc", "--prune=now", "--aggressive"],
        ]
        for cmd in cleanup_cmds:
            docker_runner.exec(
                cmd,
                workdir="/bench/repo",
                env=env,
                timeout=300,
                stdout_path=logs_dir / "clone.stdout",
                stderr_path=logs_dir / "clone.stderr",
                event_name="CLEANUP",
            )

        _check_stop()
        _check_timeout()

        # Apply prepare_patch
        prepare_path, test_path = spec.instance_config.resolve_patch_paths(spec.instance_dir)
        if prepare_path:
            r = docker_runner.exec(
                ["git", "apply", "/bench/patches/prepare.patch"],
                workdir="/bench/repo",
                env=env,
                timeout=60,
                stdout_path=logs_dir / "prepare_patch.stdout",
                stderr_path=logs_dir / "prepare_patch.stderr",
                event_name="PREPARE_PATCH",
            )
            if r.exit_code != 0:
                raise _StepFailed("prepare_patch failed", "prepare_patch", r.exit_code)

        _check_stop()
        _check_timeout()

        # before_agent hook
        hooks = spec.instance_config.hooks
        if hooks and hooks.before_agent:
            hook = hooks.before_agent
            r = docker_runner.exec(
                ["sh", "-c", hook.command],
                workdir="/bench/repo",
                env=env,
                timeout=hook.timeout_sec,
                stdout_path=logs_dir / "before_agent.stdout",
                stderr_path=logs_dir / "before_agent.stderr",
                event_name="BEFORE_AGENT",
            )
            if r.exit_code != 0 or r.timed_out:
                raise _StepFailed("before_agent failed", "before_agent", r.exit_code)

        _check_stop()
        _check_timeout()

        # Run agent
        adapter = build_adapter(spec.agent_entry.agent, spec.agent_entry.command, [])
        agent_cmd = adapter.build_command(spec.instance_config.prompt, execution_mode="docker")
        agent_timeout = spec.instance_config.instance_timeout_sec or 7200

        _log_agent_invocation(task_logger, agent_cmd, spec.instance_config.prompt, env)
        _copy_auth_session_file_if_needed(spec, adapter, docker_runner, dk)
        agent_step = docker_runner.exec(
            agent_cmd,
            workdir="/bench/repo",
            env=env,
            timeout=agent_timeout,
            stdout_path=logs_dir / "agent.stdout",
            stderr_path=logs_dir / "agent.stderr",
            event_name="AGENT",
            log_extra={"agent": spec.agent_entry.agent},
        )

        stdout_data = (logs_dir / "agent.stdout").read_bytes()
        stderr_data = (logs_dir / "agent.stderr").read_bytes()
        agent_run = adapter.parse_result(
            stdout_data, stderr_data, agent_step.exit_code, agent_step.duration_ms
        )
        task_logger.info(
            "AGENT_END",
            duration_ms=agent_run.duration_ms,
            exit_code=agent_step.exit_code,
            turns=agent_run.turns,
            input_tokens=agent_run.input_tokens,
            cost_usd=agent_run.cost_usd,
            cost_credits=agent_run.cost_credits,
        )
        _snapshot_agent_patch_docker(spec, docker_runner, env, logs_dir, task_logger)
        modified_files = _modified_files_docker(docker_runner, env, logs_dir)
        _warn_if_agent_succeeded_without_changes(
            task_logger,
            agent_run,
            _agent_patch_path(spec),
            modified_files,
        )

        # Apply test_patch
        if test_path:
            _log_patch_context(
                test_path,
                modified_files,
                task_logger,
                "test_patch",
            )
            r = dk.apply_patch(
                docker_runner,
                "/bench/patches/test.patch",
                "/bench/repo",
                env,
                logs_dir,
                "test_patch",
            )
            if r.exit_code != 0:
                raise _StepFailed("test_patch failed", "test_patch", r.exit_code)

        _check_stop()
        _check_timeout()

        # before_checks hook
        if hooks and hooks.before_checks:
            hook = hooks.before_checks
            r = docker_runner.exec(
                ["sh", "-c", hook.command],
                workdir="/bench/repo",
                env=env,
                timeout=hook.timeout_sec,
                stdout_path=logs_dir / "before_checks.stdout",
                stderr_path=logs_dir / "before_checks.stderr",
                event_name="BEFORE_CHECKS",
            )
            if r.exit_code != 0 or r.timed_out:
                raise _StepFailed("before_checks failed", "before_checks", r.exit_code)

        # Run checks
        for check in spec.instance_config.check_commands:
            _check_stop()
            _check_timeout()

            task_logger.info("CHECK_START", name=check.name, command=check.command)
            check_start = time.monotonic()
            r = docker_runner.exec(
                ["sh", "-c", check.command],
                workdir="/bench/repo",
                env=env,
                timeout=check.timeout_sec,
                stdout_path=logs_dir / f"check_{check.name}.stdout",
                stderr_path=logs_dir / f"check_{check.name}.stderr",
                event_name=f"CHECK_{check.name.upper()}",
            )
            check_dur = time.monotonic() - check_start
            if r.timed_out:
                status = "error"
            elif r.exit_code == 0:
                status = "pass"
            else:
                status = "fail"

            checks.append(
                CheckResult(
                    name=check.name,
                    status=status,
                    exit_code=r.exit_code,
                    duration_seconds=round(check_dur, 3),
                )
            )
            task_logger.info("CHECK_END", name=check.name, status=status, duration_ms=r.duration_ms)

    except _StepFailed as exc:
        fail_step = exc.step
        fail_exit_code = exc.exit_code
        task_logger.error("TASK_FAIL", reason=exc.reason, step=exc.step)
    except Exception as exc:
        fail_step = "unexpected"
        fail_exit_code = -1
        task_logger.error("TASK_FAIL", reason=str(exc)[:500], step="unexpected")
    finally:
        if timer:
            timer.cancel()
        if docker_runner:
            docker_runner.stop_and_remove()

    duration_seconds = round(time.monotonic() - start_time, 1)
    instance_status = (
        "pass"
        if checks and all(c.status == "pass" for c in checks) and fail_step is None
        else "fail"
    )

    result = InstanceResult(
        instance_id=spec.instance_id,
        agent=spec.agent_entry.id,
        agent_session_id=(agent_run.agent_session_id if agent_run else ""),
        repo=spec.instance_config.repo,
        base_commit=spec.instance_config.base_commit,
        status=instance_status,
        duration_seconds=duration_seconds,
        agent_stats=_build_agent_stats(agent_run),
        checks=checks,
    )

    _write_result_atomic(result, _result_path(spec))
    task_logger.info("TASK_END", status=instance_status, duration_seconds=duration_seconds)
    console.task_end(
        instance=spec.instance_id,
        agent=spec.agent_entry.id,
        status=instance_status,
        duration=duration_seconds,
        turns=agent_run.turns if agent_run else None,
        input_tokens=agent_run.input_tokens if agent_run else None,
        cost_usd=agent_run.cost_usd if agent_run else None,
        cost_credits=agent_run.cost_credits if agent_run else None,
        fail_step=fail_step,
        fail_exit_code=fail_exit_code,
    )
    task_logger.close()
    _emit_task_runner_log(spec, console)
    return result


def _fail_result(
    spec: TaskSpec,
    start_time: float,
    reason: str,
    step: str,
    task_logger: RunnerLogger,
    console: ConsoleOutput,
) -> InstanceResult:
    duration_seconds = round(time.monotonic() - start_time, 1)
    task_logger.error("TASK_FAIL", reason=reason, step=step)
    result = InstanceResult(
        instance_id=spec.instance_id,
        agent=spec.agent_entry.id,
        repo=spec.instance_config.repo,
        base_commit=spec.instance_config.base_commit,
        status="fail",
        duration_seconds=duration_seconds,
        agent_stats=AgentStats(),
        checks=[],
    )
    _write_result_atomic(result, _result_path(spec))
    task_logger.info("TASK_END", status="fail", duration_seconds=duration_seconds)
    console.task_end(
        spec.instance_id,
        spec.agent_entry.id,
        "fail",
        duration_seconds,
        fail_step=step,
    )
    task_logger.close()
    _emit_task_runner_log(spec, console)
    return result


def run_task(
    spec: TaskSpec,
    run_logger: RunnerLogger,
    console: ConsoleOutput,
) -> InstanceResult:
    """Entry point for a worker thread."""
    try:
        if spec.mode == "local":
            return _run_local(spec, run_logger, console)
        elif spec.mode == "docker":
            return _run_docker(spec, run_logger, console)
        else:
            raise ValueError(f"Unknown mode: {spec.mode}")
    except Exception as exc:
        task_logs_dir = _task_logs_dir(spec)
        task_logger = RunnerLogger(task_logs_dir / "runner.log")
        return _fail_result(
            spec, time.monotonic(), str(exc)[:500], "unexpected", task_logger, console
        )
