import os
import subprocess
from pathlib import Path

from benchrail.runner.local import apply_patch
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
