"""Local executor: runs commands directly on the runner host."""

from __future__ import annotations

import shutil
import subprocess
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from io import BufferedReader
from pathlib import Path

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


def copy_environment(src_dir: Path, dst_dir: Path) -> None:
    """Copy all files from src_dir to dst_dir."""
    if not src_dir.exists():
        return
    dst_dir.mkdir(parents=True, exist_ok=True)
    for item in src_dir.iterdir():
        dst = dst_dir / item.name
        if item.is_dir():
            shutil.copytree(item, dst, dirs_exist_ok=True)
        else:
            shutil.copy2(item, dst)


def copy_environment_layers(src_dirs: list[Path], dst_dir: Path) -> None:
    """Copy environment directories in order, letting later sources replace earlier files."""
    for src_dir in src_dirs:
        copy_environment(src_dir, dst_dir)


def _git_commit_in_base_history(
    git_runner: Callable[..., subprocess.CompletedProcess[bytes]], commit: str, base_commit: str
) -> bool:
    """Return whether commit is base_commit or one of its ancestors."""
    result = git_runner("merge-base", "--is-ancestor", commit, base_commit)
    return result.returncode == 0


def _git_commits_outside_base_history(
    git_runner: Callable[..., subprocess.CompletedProcess[bytes]], base_commit: str
) -> list[str]:
    """Return commits referenced by refs that are not reachable from base_commit."""
    result = git_runner("rev-list", "--all", "--not", base_commit)
    return [line for line in result.stdout.decode().splitlines() if line]


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

    # Clone
    clone_result = run_command(
        ["git", "clone", repo_url, str(repo_dir)],
        cwd=parent_dir,
        env=env,
        timeout=600,
        stdout_path=logs_dir / "clone.stdout",
        stderr_path=logs_dir / "clone.stderr",
        logger=logger,
        event_name="CLONE",
        log_extra={"repo": repo_url, "commit": base_commit},
    )
    if clone_result.exit_code != 0 or clone_result.timed_out:
        return f"clone failed (exit_code={clone_result.exit_code})"

    def _git(*args: str, timeout: int = 120) -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(
            ["git", *args],
            cwd=str(repo_dir),
            env=env,
            capture_output=True,
            timeout=timeout,
        )

    logger.info("CLEANUP_START")
    cleanup_start = time.monotonic()

    # Reset to base_commit
    r = _git("reset", "--hard", base_commit)
    if r.returncode != 0:
        err = r.stderr.decode("utf-8", errors="replace")[:500]
        logger.error("CLEANUP_FAILED", step="reset", stderr_tail=err)
        return f"git reset failed: {err}"

    # Remove origin
    _git("remote", "remove", "origin")

    # Delete tags that point outside base_commit history.
    r = _git("tag", "-l")
    tags = [t for t in r.stdout.decode().strip().splitlines() if t]
    for tag in tags:
        r2 = _git("rev-list", "-n", "1", tag)
        tag_commit = r2.stdout.decode().strip()
        if tag_commit and not _git_commit_in_base_history(_git, tag_commit, base_commit):
            _git("tag", "-d", tag)

    # Expire reflog and gc
    _git("reflog", "expire", "--expire=now", "--all", timeout=60)
    _git("gc", "--prune=now", "--aggressive", timeout=300)

    # Verify refs expose only base_commit and its ancestors.
    outside_history = _git_commits_outside_base_history(_git, base_commit)
    if outside_history:
        logger.error(
            "CLEANUP_FAILED",
            step="verify",
            detail="commits found after base_commit",
            commit_sample=outside_history[0],
        )
        return "git cleanup verification failed: commits found after base_commit"

    cleanup_ms = int((time.monotonic() - cleanup_start) * 1000)
    logger.info("CLEANUP_END", duration_ms=cleanup_ms, exit_code=0)
    return None


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
