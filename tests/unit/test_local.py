import os
import subprocess
from pathlib import Path

from benchrail.runner.local import (
    _git_commit_in_base_history,
    _git_commits_outside_base_history,
    apply_patch,
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

    def git_runner(*args: str) -> subprocess.CompletedProcess[bytes]:
        return _git(repo, *args, check=False)

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

    def git_runner(*args: str) -> subprocess.CompletedProcess[bytes]:
        return _git(repo, *args, check=False)

    assert _git_commit_in_base_history(git_runner, future_commit, base_commit) is False
    assert _git_commits_outside_base_history(git_runner, base_commit) == [future_commit]


def test_apply_patch_logs_precheck_failure_on_conflict(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    logs = tmp_path / "logs"
    repo.mkdir()
    logs.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.name", "Test User")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "commit.gpgsign", "false")

    file_path = repo / "a.txt"
    file_path.write_text("one\n", encoding="utf-8")
    _git(repo, "add", "a.txt")
    _git(repo, "commit", "-m", "base")

    patch_path = tmp_path / "test.patch"
    patch_path.write_text(
        """diff --git a/a.txt b/a.txt
--- a/a.txt
+++ b/a.txt
@@ -1 +1 @@
-one
+two
""",
        encoding="utf-8",
    )

    file_path.write_text("other\n", encoding="utf-8")

    logger = RunnerLogger(tmp_path / "runner.log")
    try:
        result = apply_patch(
            patch_path=patch_path,
            repo_dir=repo,
            env=os.environ.copy(),
            logs_dir=logs,
            log_prefix="test_patch",
            logger=logger,
        )
    finally:
        logger.close()

    assert result.exit_code != 0
    assert (logs / "test_patch.check.stderr").read_text(encoding="utf-8")
    runner_log = (tmp_path / "runner.log").read_text(encoding="utf-8")
    assert "TEST_PATCH_CHECK_FAILED" in runner_log
    assert "TEST_PATCH_PRECHECK_FAILED" in runner_log
