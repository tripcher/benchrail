"""Local executor: runs commands directly on the runner host."""

from __future__ import annotations

import subprocess
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass
from io import BufferedReader
from pathlib import Path

from benchrail.runner.git import GitCommandResult, setup_and_cleanup_repository
from benchrail.runner.logging_util import RunnerLogger, TruncatingWriter


@dataclass
class StepResult:
    exit_code: int
    duration_ms: int
    timed_out: bool = False
    stderr_tail: str = ""


def _read_tail(data: bytes, max_bytes: int = 500) -> str:
    tail = data[-max_bytes:] if len(data) > max_bytes else data
    return tail.decode("utf-8", errors="replace").strip()


def run_command(
    cmd: list[str] | str,
    cwd: Path,
    env: dict[str, str],
    timeout: int,
    stdout_path: Path,
    stderr_path: Path,
    logger: RunnerLogger,
    event_name: str,
    shell: bool = False,
    log_extra: Mapping[str, object] | None = None,
) -> StepResult:
    """Run a command on the local host, stream output to files."""
    extra = log_extra or {}
    logger.info(f"{event_name}_START", **extra)
    start = time.monotonic()

    stdout_w = TruncatingWriter(stdout_path, logger)
    stderr_w = TruncatingWriter(stderr_path, logger)
    stderr_buf: list[bytes] = []

    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(cwd),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=shell,
        )

        def _copy(
            src: BufferedReader | None,
            writer: TruncatingWriter,
            buf: list[bytes] | None = None,
        ) -> None:
            if src is None:
                return
            while True:
                chunk = src.read(8192)
                if not chunk:
                    break
                writer.write(chunk)
                if buf is not None:
                    buf.append(chunk)

        t_out = threading.Thread(target=_copy, args=(proc.stdout, stdout_w), daemon=True)
        t_err = threading.Thread(
            target=_copy, args=(proc.stderr, stderr_w, stderr_buf), daemon=True
        )
        t_out.start()
        t_err.start()

        timed_out = False
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            timed_out = True
        finally:
            t_out.join(timeout=5)
            t_err.join(timeout=5)

        exit_code = proc.returncode
        duration_ms = int((time.monotonic() - start) * 1000)
        stderr_data = b"".join(stderr_buf)
        stderr_tail = _read_tail(stderr_data) if exit_code != 0 or timed_out else ""

        if timed_out:
            logger.warn(
                f"{event_name}_TIMEOUT",
                elapsed_ms=duration_ms,
                limit_ms=timeout * 1000,
            )
            return StepResult(
                exit_code=-1, duration_ms=duration_ms, timed_out=True, stderr_tail=stderr_tail
            )

        log_kw: dict[str, object] = {"duration_ms": duration_ms, "exit_code": exit_code}
        log_kw.update(extra)
        if exit_code != 0:
            logger.error(f"{event_name}_FAILED", stderr_tail=stderr_tail, **log_kw)
        else:
            logger.info(f"{event_name}_END", **log_kw)

        return StepResult(exit_code=exit_code, duration_ms=duration_ms, stderr_tail=stderr_tail)

    finally:
        stdout_w.close()
        stderr_w.close()


def setup_repository(
    repo_url: str,
    base_commit: str,
    repo_dir: Path,
    parent_dir: Path,
    env: dict[str, str],
    logs_dir: Path,
    logger: RunnerLogger,
) -> str | None:
    """Clone and prepare repository. Returns error message or None on success."""

    class _LocalGitExecutor:
        def run(
            self,
            cmd: list[str],
            *,
            workdir: str | Path,
            env: dict[str, str],
            timeout: int,
            stdout_path: Path,
            stderr_path: Path,
            event_name: str,
            log_extra: Mapping[str, object] | None = None,
        ) -> GitCommandResult:
            result = run_command(
                cmd,
                cwd=Path(workdir),
                env=env,
                timeout=timeout,
                stdout_path=stdout_path,
                stderr_path=stderr_path,
                logger=logger,
                event_name=event_name,
                log_extra=log_extra,
            )
            stdout = stdout_path.read_bytes() if stdout_path.exists() else b""
            stderr = stderr_path.read_bytes() if stderr_path.exists() else b""
            return GitCommandResult(
                exit_code=result.exit_code,
                duration_ms=result.duration_ms,
                stdout=stdout,
                stderr=stderr,
                timed_out=result.timed_out,
                stderr_tail=result.stderr_tail,
            )

    return setup_and_cleanup_repository(
        repo_url=repo_url,
        base_commit=base_commit,
        repo_dir=repo_dir,
        clone_workdir=parent_dir,
        env=env,
        logs_dir=logs_dir,
        logger=logger,
        executor=_LocalGitExecutor(),
    )


def apply_patch(
    patch_path: Path,
    repo_dir: Path,
    env: dict[str, str],
    logs_dir: Path,
    log_prefix: str,
    logger: RunnerLogger,
) -> StepResult:
    precheck = run_command(
        ["git", "apply", "--check", str(patch_path)],
        cwd=repo_dir,
        env=env,
        timeout=60,
        stdout_path=logs_dir / f"{log_prefix}.check.stdout",
        stderr_path=logs_dir / f"{log_prefix}.check.stderr",
        logger=logger,
        event_name=f"{log_prefix.upper()}_CHECK",
        log_extra={
            "path": str(patch_path),
            "check_only": True,
            "note": "patch applicability depends on repository state after agent changes",
        },
    )
    if precheck.exit_code != 0 or precheck.timed_out:
        logger.error(
            f"{log_prefix.upper()}_PRECHECK_FAILED",
            path=str(patch_path),
            exit_code=precheck.exit_code,
            timed_out=precheck.timed_out,
            stderr_tail=precheck.stderr_tail,
            hint="test patch may conflict with agent changes or dataset patch surface",
        )
        return precheck

    return run_command(
        ["git", "apply", str(patch_path)],
        cwd=repo_dir,
        env=env,
        timeout=60,
        stdout_path=logs_dir / f"{log_prefix}.stdout",
        stderr_path=logs_dir / f"{log_prefix}.stderr",
        logger=logger,
        event_name=log_prefix.upper(),
        log_extra={
            "path": str(patch_path),
            "check_only": False,
            "note": "patch applicability depends on repository state after agent changes",
        },
    )
