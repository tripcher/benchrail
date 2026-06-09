import os
import subprocess
from collections.abc import Mapping
from pathlib import Path

from benchrail.runner.git import (
    GitCommandResult,
    _git_commit_in_base_history,
    _git_commits_outside_base_history,
    delete_cleanup_note_refs,
    setup_and_cleanup_repository,
)
from benchrail.runner.logging_util import RunnerLogger


def _git(
    repo: Path,
    *args: str,
    env: dict[str, str] | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[bytes]:
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        env=merged_env,
        check=check,
        capture_output=True,
    )


def _make_commit(repo: Path, name: str, content: str, commit_time: str) -> str:
    (repo / name).write_text(content)
    env = {
        "GIT_AUTHOR_DATE": commit_time,
        "GIT_COMMITTER_DATE": commit_time,
    }
    _git(repo, "add", name, env=env)
    _git(repo, "commit", "-m", content, env=env)
    return _git(repo, "rev-parse", "HEAD").stdout.decode().strip()


class _SubprocessGitExecutor:
    def __init__(self, future_commit: str | None = None) -> None:
        self.future_commit = future_commit

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
        result = subprocess.run(
            cmd,
            cwd=str(workdir),
            env=env,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
        stdout_path.write_bytes(result.stdout)
        stderr_path.write_bytes(result.stderr)

        if (
            cmd[:2] == ["git", "clone"]
            and result.returncode == 0
            and self.future_commit is not None
        ):
            repo_dir = Path(cmd[-1])
            _git(repo_dir, "update-ref", "refs/notes/ai", self.future_commit)
            _git(repo_dir, "update-ref", "refs/notes/ai-remote/origin", self.future_commit)

        return GitCommandResult(
            exit_code=result.returncode,
            duration_ms=0,
            stdout=result.stdout,
            stderr=result.stderr,
            stderr_tail=result.stderr.decode("utf-8", errors="replace")[:500],
        )


def test_git_commits_outside_base_history_is_empty_for_linear_history(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.name", "Test User")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "commit.gpgsign", "false")

    _make_commit(repo, "a.txt", "first", "2024-01-01T00:00:00+0000")
    _make_commit(repo, "a.txt", "second", "2024-01-02T00:00:00+0000")
    base_commit = _make_commit(repo, "a.txt", "third", "2024-01-03T00:00:00+0000")

    def git_runner(*args: str) -> GitCommandResult:
        result = _git(repo, *args, check=False)
        return GitCommandResult(
            exit_code=result.returncode,
            duration_ms=0,
            stdout=result.stdout,
            stderr=result.stderr,
        )

    assert _git_commit_in_base_history(git_runner, base_commit, base_commit) is True
    assert _git_commits_outside_base_history(git_runner, base_commit) == []


def test_git_commits_outside_base_history_detects_future_tag_after_reset(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.name", "Test User")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "commit.gpgsign", "false")

    _make_commit(repo, "a.txt", "first", "2024-01-01T00:00:00+0000")
    base_commit = _make_commit(repo, "a.txt", "second", "2024-01-02T00:00:00+0000")
    future_commit = _make_commit(repo, "a.txt", "third", "2024-01-03T00:00:00+0000")
    _git(repo, "tag", "future-tag", future_commit)
    _git(repo, "reset", "--hard", base_commit)

    def git_runner(*args: str) -> GitCommandResult:
        result = _git(repo, *args, check=False)
        return GitCommandResult(
            exit_code=result.returncode,
            duration_ms=0,
            stdout=result.stdout,
            stderr=result.stderr,
        )

    assert _git_commit_in_base_history(git_runner, future_commit, base_commit) is False
    assert _git_commits_outside_base_history(git_runner, base_commit) == [future_commit]


def test_delete_cleanup_note_refs_removes_ai_note_refs(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.name", "Test User")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "commit.gpgsign", "false")

    _make_commit(repo, "a.txt", "first", "2024-01-01T00:00:00+0000")
    base_commit = _make_commit(repo, "a.txt", "second", "2024-01-02T00:00:00+0000")
    future_commit = _make_commit(repo, "a.txt", "third", "2024-01-03T00:00:00+0000")
    _git(repo, "update-ref", "refs/notes/ai", future_commit)
    _git(repo, "update-ref", "refs/notes/ai-remote/origin", future_commit)
    _git(repo, "reset", "--hard", base_commit)

    def git_runner(*args: str) -> GitCommandResult:
        result = _git(repo, *args, check=False)
        return GitCommandResult(
            exit_code=result.returncode,
            duration_ms=0,
            stdout=result.stdout,
            stderr=result.stderr,
        )

    delete_cleanup_note_refs(git_runner)

    assert _git(repo, "show-ref", "--verify", "refs/notes/ai", check=False).returncode != 0
    assert (
        _git(repo, "show-ref", "--verify", "refs/notes/ai-remote/origin", check=False).returncode
        != 0
    )
    assert _git_commits_outside_base_history(git_runner, base_commit) == []


def test_git_commits_outside_base_history_ignores_ai_note_refs(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.name", "Test User")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "commit.gpgsign", "false")

    _make_commit(repo, "a.txt", "first", "2024-01-01T00:00:00+0000")
    base_commit = _make_commit(repo, "a.txt", "second", "2024-01-02T00:00:00+0000")
    future_commit = _make_commit(repo, "a.txt", "third", "2024-01-03T00:00:00+0000")
    _git(repo, "update-ref", "refs/notes/ai", future_commit)
    _git(repo, "update-ref", "refs/notes/ai-remote/origin", future_commit)
    _git(repo, "reset", "--hard", base_commit)

    def git_runner(*args: str) -> GitCommandResult:
        result = _git(repo, *args, check=False)
        return GitCommandResult(
            exit_code=result.returncode,
            duration_ms=0,
            stdout=result.stdout,
            stderr=result.stderr,
        )

    assert _git_commits_outside_base_history(git_runner, base_commit) == []


def test_setup_and_cleanup_repository_uses_shared_git_flow(tmp_path: Path) -> None:
    source_repo = tmp_path / "source"
    source_repo.mkdir()
    _git(source_repo, "init", "-b", "main")
    _git(source_repo, "config", "user.name", "Test User")
    _git(source_repo, "config", "user.email", "test@example.com")
    _git(source_repo, "config", "commit.gpgsign", "false")

    _make_commit(source_repo, "a.txt", "first", "2024-01-01T00:00:00+0000")
    base_commit = _make_commit(source_repo, "a.txt", "second", "2024-01-02T00:00:00+0000")
    future_commit = _make_commit(source_repo, "a.txt", "third", "2024-01-03T00:00:00+0000")
    _git(source_repo, "tag", "future-tag", future_commit)

    clone_repo = tmp_path / "clone"
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    logger = RunnerLogger(tmp_path / "runner.log")

    try:
        err = setup_and_cleanup_repository(
            repo_url=str(source_repo),
            base_commit=base_commit,
            repo_dir=clone_repo,
            clone_workdir=tmp_path,
            env=os.environ.copy(),
            logs_dir=logs_dir,
            logger=logger,
            executor=_SubprocessGitExecutor(future_commit),
        )
    finally:
        logger.close()

    assert err is None
    assert _git(clone_repo, "rev-parse", "HEAD").stdout.decode().strip() == base_commit
    assert _git(clone_repo, "remote", check=False).stdout.decode().strip() == ""
    assert _git(clone_repo, "show-ref", "--verify", "refs/notes/ai", check=False).returncode != 0
    assert (
        _git(
            clone_repo, "show-ref", "--verify", "refs/notes/ai-remote/origin", check=False
        ).returncode
        != 0
    )
    assert (
        _git(clone_repo, "show-ref", "--verify", "refs/tags/future-tag", check=False).returncode
        != 0
    )

    def git_runner(*args: str) -> GitCommandResult:
        result = _git(clone_repo, *args, check=False)
        return GitCommandResult(
            exit_code=result.returncode,
            duration_ms=0,
            stdout=result.stdout,
            stderr=result.stderr,
        )

    assert _git_commits_outside_base_history(git_runner, base_commit) == []
