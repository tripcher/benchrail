from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from benchrail.runner.logging_util import RunnerLogger

GIT_CLEANUP_NOTE_REFS = (
    "refs/notes/ai",
    "refs/notes/ai-remote/origin",
)


@dataclass
class GitCommandResult:
    exit_code: int
    duration_ms: int
    stdout: bytes
    stderr: bytes
    timed_out: bool = False
    stderr_tail: str = ""


class GitExecutor(Protocol):
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
    ) -> GitCommandResult: ...


def _stderr_tail(stderr: bytes) -> str:
    return stderr.decode("utf-8", errors="replace")[:500]


def _git_commit_in_base_history(
    git_runner: Callable[..., GitCommandResult], commit: str, base_commit: str
) -> bool:
    """Return whether commit is base_commit or one of its ancestors."""
    result = git_runner("merge-base", "--is-ancestor", commit, base_commit)
    return result.exit_code == 0


def _git_commits_outside_base_history(
    git_runner: Callable[..., GitCommandResult], base_commit: str
) -> list[str]:
    """Return commits from verification-scope refs not reachable from base_commit."""
    result = git_runner("rev-list", "--branches", "--tags", "--remotes", "--not", base_commit)
    return [line for line in result.stdout.decode().splitlines() if line]


def delete_cleanup_note_refs(
    git_runner: Callable[..., GitCommandResult],
) -> None:
    for ref in GIT_CLEANUP_NOTE_REFS:
        git_runner("update-ref", "-d", ref)


def setup_and_cleanup_repository(
    *,
    repo_url: str,
    base_commit: str,
    repo_dir: str | Path,
    clone_workdir: str | Path,
    env: dict[str, str],
    logs_dir: Path,
    logger: RunnerLogger,
    executor: GitExecutor,
) -> str | None:
    clone_result = executor.run(
        ["git", "clone", repo_url, str(repo_dir)],
        workdir=clone_workdir,
        env=env,
        timeout=600,
        stdout_path=logs_dir / "clone.stdout",
        stderr_path=logs_dir / "clone.stderr",
        event_name="CLONE",
        log_extra={"repo": repo_url, "commit": base_commit},
    )
    if clone_result.exit_code != 0 or clone_result.timed_out:
        return f"clone failed (exit_code={clone_result.exit_code})"

    logger.info("CLEANUP_START")
    cleanup_start = time.monotonic()

    def _run_git(
        *args: str,
        timeout: int = 120,
        step: str,
        log_extra: Mapping[str, object] | None = None,
    ) -> GitCommandResult:
        extra: dict[str, object] = {"step": step}
        if log_extra:
            extra.update(log_extra)
        return executor.run(
            ["git", *args],
            workdir=repo_dir,
            env=env,
            timeout=timeout,
            stdout_path=logs_dir / f"cleanup.{step}.stdout",
            stderr_path=logs_dir / f"cleanup.{step}.stderr",
            event_name="CLEANUP",
            log_extra=extra,
        )

    r = _run_git("reset", "--hard", base_commit, step="reset")
    if r.exit_code != 0:
        err = _stderr_tail(r.stderr)
        logger.error("CLEANUP_FAILED", step="reset", stderr_tail=err)
        return f"git reset failed: {err}"

    _run_git("remote", "remove", "origin", step="remove_origin")

    def _git_runner(
        *args: str,
        timeout: int = 120,
        step: str | None = None,
    ) -> GitCommandResult:
        resolved_step = step or args[0].replace("-", "_")
        return _run_git(*args, timeout=timeout, step=resolved_step)

    delete_cleanup_note_refs(_git_runner)

    tag_result = _git_runner("tag", "-l")
    tags = [tag for tag in tag_result.stdout.decode().strip().splitlines() if tag]
    for tag in tags:
        tag_commit_result = _git_runner("rev-list", "-n", "1", tag, step="tag_commit")
        tag_commit = tag_commit_result.stdout.decode().strip()
        if tag_commit and not _git_commit_in_base_history(_git_runner, tag_commit, base_commit):
            _git_runner("tag", "-d", tag, step="delete_tag")

    _git_runner("reflog", "expire", "--expire=now", "--all", timeout=60)
    _git_runner("gc", "--prune=now", "--aggressive", timeout=300)
    delete_cleanup_note_refs(_git_runner)

    outside_history = _git_commits_outside_base_history(_git_runner, base_commit)
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
