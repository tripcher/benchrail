import os
import subprocess
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from benchrail.adapters.base import AgentRunResult, BaseAdapter
from benchrail.dto.config import InstanceConfig
from benchrail.dto.manifest import AgentEntry
from benchrail.runner.logging_util import RunnerLogger
from benchrail.runner.worker import (
    TaskSpec,
    _agent_runtime_env,
    _apply_codex_exec_auth_env,
    _copy_auth_session_file_if_needed,
    _emit_task_runner_log,
    _log_patch_context,
    _parse_patch_touched_files,
    _resolve_docker_env,
    _snapshot_agent_patch_baseline_local,
    _snapshot_agent_patch_local,
    _write_expected_migration_diff,
)


class _FakeAdapter(BaseAdapter):
    def __init__(self, session_file: Path | None) -> None:
        super().__init__()
        self._session_file = session_file

    def _base_command(self, execution_mode: str) -> list[str]:
        return ["fake"]

    def auth_session_file(self) -> Path | None:
        return self._session_file

    def parse_result(
        self,
        stdout: bytes,
        stderr: bytes,
        exit_code: int,
        duration_ms: int,
    ) -> AgentRunResult:
        raise NotImplementedError


class _FakeConsole:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def print(self, msg: str) -> None:
        self.messages.append(msg)


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        env=os.environ.copy(),
        check=True,
        capture_output=True,
    )


def test_agent_runtime_env_maps_codex_version() -> None:
    agent = AgentEntry(id="codex-test", agent="codex", version="0.136.0")
    assert _agent_runtime_env(agent, {}) == {"BENCH_ENV_CODEX_VERSION": "0.136.0"}


def test_agent_runtime_env_defaults_to_latest() -> None:
    agent = AgentEntry(id="codex-test", agent="codex", version="")
    assert _agent_runtime_env(agent, {}) == {"BENCH_ENV_CODEX_VERSION": "latest"}


def test_agent_runtime_env_preserves_explicit_value() -> None:
    agent = AgentEntry(id="codex-test", agent="codex", version="latest")
    existing = {"BENCH_ENV_CODEX_VERSION": "0.135.0"}
    assert _agent_runtime_env(agent, existing) == {}


def test_agent_runtime_env_maps_claude_code_version() -> None:
    agent = AgentEntry(id="claude-test", agent="claude-code", version="1.2.3")
    assert _agent_runtime_env(agent, {}) == {"BENCH_ENV_CLAUDE_CODE_VERSION": "1.2.3"}


def test_agent_runtime_env_ignores_unknown_agent() -> None:
    agent = AgentEntry(id="other-test", agent="other-agent", version="9.9.9")
    assert _agent_runtime_env(agent, {}) == {}


def test_apply_codex_exec_auth_env_copies_openai_key() -> None:
    env = {"OPENAI_API_KEY": "sk-test"}
    _apply_codex_exec_auth_env("codex", env)
    assert env["CODEX_API_KEY"] == "sk-test"


def test_resolve_docker_env_accepts_codex_api_key_for_openai_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("CODEX_API_KEY", "sk-codex")
    spec = TaskSpec(
        instance_id="task-1",
        agent_entry=AgentEntry(id="codex-test", agent="codex", version="latest"),
        instance_config=InstanceConfig.model_validate(
            {
                "instance_id": "task-1",
                "repo": "https://github.com/example/repo.git",
                "base_commit": "abc123",
                "prompt": "Fix the bug",
                "docker": {
                    "image": "benchrail-universal:latest",
                    "env_from_host": ["OPENAI_API_KEY"],
                },
                "check_commands": [{"name": "tests", "command": "make test", "timeout_sec": 300}],
            }
        ),
        instance_dir=Path("/tmp/task-1"),
        workspace_root=Path("/tmp/workspace"),
        output_root=None,
        logs_root=Path("/tmp/logs"),
        run_id="run-1",
        mode="docker",
        auth_session=False,
        stop_flag=threading.Event(),
    )

    env = _resolve_docker_env(spec)
    assert env["OPENAI_API_KEY"] == "sk-codex"
    assert env["CODEX_API_KEY"] == "sk-codex"


def test_copy_auth_session_file_if_needed_uses_adapter_session_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    auth_home = tmp_path / "home"
    auth_dir = auth_home / ".codex"
    auth_dir.mkdir(parents=True)
    auth_json = auth_dir / "auth.json"
    auth_json.write_text('{"method":"chatgpt"}', encoding="utf-8")
    monkeypatch.setattr(Path, "home", lambda: auth_home)

    spec = TaskSpec(
        instance_id="task-1",
        agent_entry=AgentEntry(id="codex-test", agent="codex", version="latest"),
        instance_config=InstanceConfig.model_validate(
            {
                "instance_id": "task-1",
                "repo": "https://github.com/example/repo.git",
                "base_commit": "abc123",
                "prompt": "Fix the bug",
                "docker": {
                    "image": "benchrail-universal:latest",
                },
                "check_commands": [{"name": "tests", "command": "make test", "timeout_sec": 300}],
            }
        ),
        instance_dir=Path("/tmp/task-1"),
        workspace_root=Path("/tmp/workspace"),
        output_root=None,
        logs_root=Path("/tmp/logs"),
        run_id="run-1",
        mode="docker",
        auth_session=True,
        stop_flag=threading.Event(),
    )

    calls: list[tuple[Path, str, str]] = []
    docker_module = SimpleNamespace(
        copy_file_to_container=lambda runner, src_file, dst_dir, dst_relpath: calls.append(
            (src_file, dst_dir, dst_relpath)
        )
    )
    _copy_auth_session_file_if_needed(
        spec,
        _FakeAdapter(auth_json),
        object(),
        docker_module,
    )
    assert calls == [(auth_json, "/root", ".codex/auth.json")]


def test_copy_auth_session_file_if_needed_skips_without_flag(tmp_path: Path) -> None:
    auth_json = tmp_path / ".codex" / "auth.json"
    auth_json.parent.mkdir(parents=True)
    auth_json.write_text("{}", encoding="utf-8")
    spec = TaskSpec(
        instance_id="task-1",
        agent_entry=AgentEntry(id="codex-test", agent="codex", version="latest"),
        instance_config=InstanceConfig.model_validate(
            {
                "instance_id": "task-1",
                "repo": "https://github.com/example/repo.git",
                "base_commit": "abc123",
                "prompt": "Fix the bug",
                "docker": {
                    "image": "benchrail-universal:latest",
                },
                "check_commands": [{"name": "tests", "command": "make test", "timeout_sec": 300}],
            }
        ),
        instance_dir=Path("/tmp/task-1"),
        workspace_root=Path("/tmp/workspace"),
        output_root=None,
        logs_root=Path("/tmp/logs"),
        run_id="run-1",
        mode="docker",
        auth_session=False,
        stop_flag=threading.Event(),
    )

    calls: list[tuple[Path, str, str]] = []
    docker_module = SimpleNamespace(
        copy_file_to_container=lambda runner, src_file, dst_dir, dst_relpath: calls.append(
            (src_file, dst_dir, dst_relpath)
        )
    )
    _copy_auth_session_file_if_needed(
        spec,
        _FakeAdapter(auth_json),
        object(),
        docker_module,
    )
    assert calls == []


def test_copy_auth_session_file_if_needed_requires_existing_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    spec = TaskSpec(
        instance_id="task-1",
        agent_entry=AgentEntry(id="codex-test", agent="codex", version="latest"),
        instance_config=InstanceConfig.model_validate(
            {
                "instance_id": "task-1",
                "repo": "https://github.com/example/repo.git",
                "base_commit": "abc123",
                "prompt": "Fix the bug",
                "docker": {
                    "image": "benchrail-universal:latest",
                },
                "check_commands": [{"name": "tests", "command": "make test", "timeout_sec": 300}],
            }
        ),
        instance_dir=Path("/tmp/task-1"),
        workspace_root=Path("/tmp/workspace"),
        output_root=None,
        logs_root=Path("/tmp/logs"),
        run_id="run-1",
        mode="docker",
        auth_session=True,
        stop_flag=threading.Event(),
    )

    with pytest.raises(Exception, match="agent auth subscription file not found"):
        _copy_auth_session_file_if_needed(
            spec,
            _FakeAdapter(tmp_path / "home" / ".codex" / "auth.json"),
            object(),
            SimpleNamespace(copy_file_to_container=lambda *args: None),
        )


def test_parse_patch_touched_files_returns_unique_files(tmp_path: Path) -> None:
    patch = tmp_path / "test.patch"
    patch.write_text(
        """diff --git a/tests/test_a.py b/tests/test_a.py
--- a/tests/test_a.py
+++ b/tests/test_a.py
@@ -1 +1 @@
-old
+new
diff --git a/src/app.py b/src/app.py
--- a/src/app.py
+++ b/src/app.py
@@ -1 +1 @@
-x = 1
+x = 2
diff --git a/tests/test_a.py b/tests/test_a.py
--- a/tests/test_a.py
+++ b/tests/test_a.py
@@ -2 +2 @@
-again
+again2
""".replace("++++", "+++"),
        encoding="utf-8",
    )

    assert _parse_patch_touched_files(patch) == ["tests/test_a.py", "src/app.py"]


def test_log_patch_context_reports_overlap(tmp_path: Path) -> None:
    patch = tmp_path / "test.patch"
    patch.write_text(
        """diff --git a/tests/test_a.py b/tests/test_a.py
--- a/tests/test_a.py
+++ b/tests/test_a.py
@@ -1 +1 @@
-old
+new
diff --git a/src/app.py b/src/app.py
--- a/src/app.py
+++ b/src/app.py
@@ -1 +1 @@
-x = 1
+x = 2
""".replace("++++", "+++"),
        encoding="utf-8",
    )
    log_path = tmp_path / "runner.log"
    logger = RunnerLogger(log_path)
    try:
        _log_patch_context(
            patch,
            ["tests/test_a.py", "docs/readme.md"],
            logger,
            "test_patch",
        )
    finally:
        logger.close()

    log_text = log_path.read_text(encoding="utf-8")
    assert "TEST_PATCH_CONTEXT" in log_text
    assert "TEST_PATCH_OVERLAP" in log_text
    assert "tests/test_a.py" in log_text


def test_snapshot_agent_patch_local_excludes_pre_agent_environment_changes(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.name", "Test User")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "commit.gpgsign", "false")
    (repo / "app.py").write_text("value = 'base'\n", encoding="utf-8")
    _git(repo, "add", "app.py")
    _git(repo, "commit", "-m", "base")

    spec = TaskSpec(
        instance_id="task-1",
        agent_entry=AgentEntry(id="codex-test", agent="codex", version="latest"),
        instance_config=InstanceConfig.model_validate(
            {
                "instance_id": "task-1",
                "repo": "https://github.com/example/repo.git",
                "base_commit": "abc123",
                "prompt": "Fix the bug",
                "check_commands": [{"name": "tests", "command": "make test", "timeout_sec": 300}],
            }
        ),
        instance_dir=tmp_path / "dataset" / "task-1",
        workspace_root=tmp_path / "workspace",
        output_root=None,
        logs_root=tmp_path / "logs",
        run_id="run-1",
        mode="local",
        auth_session=False,
        stop_flag=threading.Event(),
    )
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    task_logger = RunnerLogger(tmp_path / "runner.log")
    try:
        (repo / "app.py").write_text("value = 'prepared'\n", encoding="utf-8")
        (repo / "setup_only.txt").write_text("from before_agent\n", encoding="utf-8")

        baseline = _snapshot_agent_patch_baseline_local(
            repo,
            os.environ.copy(),
            logs_dir,
            task_logger,
        )
        assert baseline is not None

        (repo / "app.py").write_text("value = 'agent'\n", encoding="utf-8")
        (repo / "agent_only.txt").write_text("from agent\n", encoding="utf-8")

        _snapshot_agent_patch_local(
            spec,
            repo,
            os.environ.copy(),
            logs_dir,
            task_logger,
            baseline,
        )
    finally:
        task_logger.close()

    patch_text = (
        spec.workspace_root / spec.run_id / spec.agent_entry.id / spec.instance_id / "agent.patch"
    ).read_text(encoding="utf-8")
    assert "setup_only.txt" not in patch_text
    assert "agent_only.txt" in patch_text
    assert "-value = 'prepared'" in patch_text
    assert "+value = 'agent'" in patch_text


def test_write_expected_migration_diff_writes_artifact_in_result_dir(tmp_path: Path) -> None:
    spec = TaskSpec(
        instance_id="task-1",
        agent_entry=AgentEntry(id="codex-test", agent="codex", version="latest"),
        instance_config=InstanceConfig.model_validate(
            {
                "instance_id": "task-1",
                "repo": "https://github.com/example/repo.git",
                "base_commit": "abc123",
                "prompt": "Fix the bug",
                "docker": {"image": "benchrail-universal:latest"},
                "check_commands": [{"name": "tests", "command": "make test", "timeout_sec": 300}],
            }
        ),
        instance_dir=tmp_path / "dataset" / "task-1",
        workspace_root=tmp_path / "workspace",
        output_root=None,
        logs_root=tmp_path / "logs",
        run_id="run-1",
        mode="local",
        auth_session=False,
        stop_flag=threading.Event(),
    )
    spec.instance_dir.mkdir(parents=True)
    (spec.instance_dir / "expected_migration.json").write_text(
        '{\n  "migration": "expected"\n}\n',
        encoding="utf-8",
    )
    result_dir = spec.workspace_root / spec.run_id / spec.agent_entry.id / spec.instance_id
    result_dir.mkdir(parents=True)
    (result_dir / "agent.patch").write_text(
        """diff --git a/migration.json b/migration.json
new file mode 100644
--- /dev/null
+++ b/migration.json
@@ -0,0 +1,3 @@
+{
+  "migration": "actual"
+}
""".replace("++++", "+++"),
        encoding="utf-8",
    )
    logger = RunnerLogger(tmp_path / "runner.log")
    try:
        _write_expected_migration_diff(spec, logger)
    finally:
        logger.close()

    diff_path = result_dir / "expected_migration_vs_agent_patch.diff"
    assert diff_path.exists()
    diff_text = diff_path.read_text(encoding="utf-8")
    assert "--- expected_migration.json" in diff_text
    assert "+++ agent.patch" in diff_text
    assert '"migration": "expected"' in diff_text
    assert '"migration": "actual"' in diff_text


def test_emit_task_runner_log_prints_full_log(tmp_path: Path) -> None:
    spec = TaskSpec(
        instance_id="task-1",
        agent_entry=AgentEntry(id="codex-test", agent="codex", version="latest"),
        instance_config=InstanceConfig.model_validate(
            {
                "instance_id": "task-1",
                "repo": "https://github.com/example/repo.git",
                "base_commit": "abc123",
                "prompt": "Fix the bug",
                "docker": {"image": "benchrail-universal:latest"},
                "check_commands": [{"name": "tests", "command": "make test", "timeout_sec": 300}],
            }
        ),
        instance_dir=tmp_path / "dataset" / "task-1",
        workspace_root=tmp_path / "workspace",
        output_root=None,
        logs_root=tmp_path / "logs",
        run_id="run-1",
        mode="docker",
        auth_session=False,
        stop_flag=threading.Event(),
    )
    log_dir = spec.logs_root / spec.run_id / spec.agent_entry.id / spec.instance_id
    log_dir.mkdir(parents=True)
    log_path = log_dir / "runner.log"
    log_path.write_text("line1\nline2\n", encoding="utf-8")
    console = _FakeConsole()

    _emit_task_runner_log(spec, console)

    assert len(console.messages) == 1
    assert "RUNNER_LOG instance=task-1 agent=codex-test" in console.messages[0]
    assert "line1\nline2" in console.messages[0]
    assert "END_RUNNER_LOG instance=task-1 agent=codex-test" in console.messages[0]


def test_emit_task_runner_log_reports_missing_file(tmp_path: Path) -> None:
    spec = TaskSpec(
        instance_id="task-1",
        agent_entry=AgentEntry(id="codex-test", agent="codex", version="latest"),
        instance_config=InstanceConfig.model_validate(
            {
                "instance_id": "task-1",
                "repo": "https://github.com/example/repo.git",
                "base_commit": "abc123",
                "prompt": "Fix the bug",
                "docker": {"image": "benchrail-universal:latest"},
                "check_commands": [{"name": "tests", "command": "make test", "timeout_sec": 300}],
            }
        ),
        instance_dir=tmp_path / "dataset" / "task-1",
        workspace_root=tmp_path / "workspace",
        output_root=None,
        logs_root=tmp_path / "logs",
        run_id="run-1",
        mode="docker",
        auth_session=False,
        stop_flag=threading.Event(),
    )
    console = _FakeConsole()

    _emit_task_runner_log(spec, console)

    assert len(console.messages) == 1
    assert "[missing runner.log]" in console.messages[0]
