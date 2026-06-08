"""Tests for DTO models."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from benchrail.dto.config import CheckCommand, InstanceConfig
from benchrail.dto.manifest import AgentEntry, Manifest
from benchrail.dto.result import AgentStats, CheckResult, InstanceResult, RunResult

# ─── Manifest ────────────────────────────────────────────────────────────────


def test_manifest_valid() -> None:
    data = {
        "agents": [
            {
                "id": "claude-code-sonnet",
                "agent": "claude-code",
                "version": "2.1.81",
                "command": "--model claude-sonnet-4-6",
            }
        ]
    }
    m = Manifest.model_validate(data)
    assert len(m.agents) == 1
    assert m.agents[0].id == "claude-code-sonnet"


def test_manifest_empty_agents() -> None:
    with pytest.raises(ValidationError, match="agents"):
        Manifest.model_validate({"agents": []})


def test_manifest_duplicate_ids() -> None:
    data = {
        "agents": [
            {"id": "agent-1", "agent": "claude-code"},
            {"id": "agent-1", "agent": "codex"},
        ]
    }
    with pytest.raises(ValidationError, match="Duplicate"):
        Manifest.model_validate(data)


def test_agent_entry_invalid_id() -> None:
    with pytest.raises(ValidationError):
        AgentEntry(id="my agent!", agent="claude-code")


# ─── InstanceConfig ───────────────────────────────────────────────────────────


def test_instance_config_valid() -> None:
    data = {
        "instance_id": "task-1",
        "repo": "https://github.com/example/repo.git",
        "base_commit": "abc123",
        "prompt": "Fix the bug",
        "check_commands": [{"name": "tests", "command": "make test", "timeout_sec": 300}],
    }
    c = InstanceConfig.model_validate(data)
    assert c.instance_id == "task-1"
    assert len(c.check_commands) == 1


def test_instance_config_docker_env_valid() -> None:
    data = {
        "instance_id": "task-1",
        "repo": "https://github.com/example/repo.git",
        "base_commit": "abc123",
        "prompt": "Fix the bug",
        "docker": {
            "image": "ghcr.io/org/sqlfluff-codex:2026-06-03",
            "env": {
                "FOO": "enabled",
            },
            "env_from_host": ["OPENAI_API_KEY"],
        },
        "check_commands": [{"name": "tests", "command": "make test", "timeout_sec": 300}],
    }
    c = InstanceConfig.model_validate(data)
    assert c.docker.image == "ghcr.io/org/sqlfluff-codex:2026-06-03"
    assert c.docker.env["FOO"] == "enabled"
    assert c.docker.env_from_host == ["OPENAI_API_KEY"]


def test_instance_config_dockerfile_valid() -> None:
    data = {
        "instance_id": "task-1",
        "repo": "https://github.com/example/repo.git",
        "base_commit": "abc123",
        "prompt": "Fix the bug",
        "docker": {
            "dockerfile": "environment/Dockerfile",
        },
        "check_commands": [{"name": "tests", "command": "make test", "timeout_sec": 300}],
    }
    c = InstanceConfig.model_validate(data)
    assert c.docker.dockerfile == "environment/Dockerfile"


def test_instance_config_docker_image_and_dockerfile_conflict() -> None:
    data = {
        "instance_id": "task-1",
        "repo": "https://github.com/example/repo.git",
        "base_commit": "abc123",
        "prompt": "Fix the bug",
        "docker": {
            "image": "ghcr.io/org/sqlfluff-codex:2026-06-03",
            "dockerfile": "environment/Dockerfile",
        },
        "check_commands": [{"name": "tests", "command": "make test", "timeout_sec": 300}],
    }
    with pytest.raises(ValidationError, match="mutually exclusive"):
        InstanceConfig.model_validate(data)


def test_instance_config_docker_env_invalid_name() -> None:
    data = {
        "instance_id": "task-1",
        "repo": "https://github.com/example/repo.git",
        "base_commit": "abc123",
        "prompt": "Fix the bug",
        "docker": {"env": {"lowercase": "bad"}},
        "check_commands": [{"name": "tests", "command": "make test", "timeout_sec": 300}],
    }
    with pytest.raises(ValidationError):
        InstanceConfig.model_validate(data)


def test_instance_config_empty_check_commands() -> None:
    data = {
        "instance_id": "task-1",
        "repo": "https://github.com/example/repo.git",
        "base_commit": "abc123",
        "prompt": "Fix the bug",
        "check_commands": [],
    }
    with pytest.raises(ValidationError, match="check_commands"):
        InstanceConfig.model_validate(data)


def test_instance_config_duplicate_check_names() -> None:
    data = {
        "instance_id": "task-1",
        "repo": "https://github.com/example/repo.git",
        "base_commit": "abc123",
        "prompt": "Fix the bug",
        "check_commands": [
            {"name": "tests", "command": "make test", "timeout_sec": 300},
            {"name": "tests", "command": "make test2", "timeout_sec": 300},
        ],
    }
    with pytest.raises(ValidationError, match="unique"):
        InstanceConfig.model_validate(data)


def test_instance_config_negative_timeout() -> None:
    with pytest.raises(ValidationError):
        CheckCommand(name="tests", command="make test", timeout_sec=-1)


def test_instance_config_resolve_patch_paths_missing(tmp_path: Path) -> None:
    data = {
        "instance_id": "task-1",
        "repo": "https://github.com/example/repo.git",
        "base_commit": "abc123",
        "prompt": "Fix",
        "check_commands": [{"name": "tests", "command": "make test", "timeout_sec": 60}],
        "prepare_patch_path": "patches/prepare.patch",
    }
    c = InstanceConfig.model_validate(data)
    with pytest.raises(ValueError, match="file not found"):
        c.resolve_patch_paths(tmp_path)


def test_instance_config_resolve_patch_paths_escape(tmp_path: Path) -> None:
    data = {
        "instance_id": "task-1",
        "repo": "https://github.com/example/repo.git",
        "base_commit": "abc123",
        "prompt": "Fix",
        "check_commands": [{"name": "tests", "command": "make test", "timeout_sec": 60}],
        "prepare_patch_path": "../../etc/passwd",
    }
    c = InstanceConfig.model_validate(data)
    with pytest.raises(ValueError, match="escape"):
        c.resolve_patch_paths(tmp_path)


def test_instance_config_resolve_dockerfile_path_missing(tmp_path: Path) -> None:
    data = {
        "instance_id": "task-1",
        "repo": "https://github.com/example/repo.git",
        "base_commit": "abc123",
        "prompt": "Fix",
        "docker": {"dockerfile": "environment/Dockerfile"},
        "check_commands": [{"name": "tests", "command": "make test", "timeout_sec": 60}],
    }
    c = InstanceConfig.model_validate(data)
    with pytest.raises(ValueError, match="file not found"):
        c.docker.resolve_dockerfile_path(tmp_path)


def test_instance_config_resolve_dockerfile_path_escape(tmp_path: Path) -> None:
    data = {
        "instance_id": "task-1",
        "repo": "https://github.com/example/repo.git",
        "base_commit": "abc123",
        "prompt": "Fix",
        "docker": {"dockerfile": "../../Dockerfile"},
        "check_commands": [{"name": "tests", "command": "make test", "timeout_sec": 60}],
    }
    c = InstanceConfig.model_validate(data)
    with pytest.raises(ValueError, match="escape"):
        c.docker.resolve_dockerfile_path(tmp_path)


# ─── Result models ───────────────────────────────────────────────────────────


def test_instance_result_serialization() -> None:
    r = InstanceResult(
        instance_id="task-1",
        agent="claude-code-sonnet",
        repo="https://github.com/example/repo.git",
        base_commit="abc123",
        status="pass",
        duration_seconds=142.7,
        agent_stats=AgentStats(
            duration_ms=98400, turns=12, input_tokens=45230, cost_credits=1.2345
        ),
        checks=[CheckResult(name="tests", status="pass", exit_code=0, duration_seconds=45.2)],
    )
    payload = json.loads(r.model_dump_json())
    assert isinstance(payload, dict)
    data = payload
    assert data["schema_version"] == "1.0"
    assert data["status"] == "pass"
    assert data["agent_stats"]["duration_ms"] == 98400
    assert data["agent_stats"]["cost_credits"] == 1.2345


def test_run_result_aggregate() -> None:
    results = [
        InstanceResult(
            instance_id="task-1",
            agent="agent-a",
            repo="r",
            base_commit="c",
            status="pass",
            duration_seconds=10.0,
            agent_stats=AgentStats(
                input_tokens=100, output_tokens=50, cost_usd=0.5, cost_credits=1.25
            ),
            checks=[CheckResult(name="tests", status="pass", exit_code=0, duration_seconds=5.0)],
        ),
        InstanceResult(
            instance_id="task-1",
            agent="agent-b",
            repo="r",
            base_commit="c",
            status="fail",
            duration_seconds=20.0,
            agent_stats=AgentStats(
                input_tokens=200, output_tokens=100, cost_usd=1.0, cost_credits=2.5
            ),
            checks=[CheckResult(name="tests", status="fail", exit_code=1, duration_seconds=3.0)],
        ),
    ]
    run = RunResult.aggregate(
        run_id="run-123",
        mode="local",
        dataset_path="dataset",
        status="completed",
        duration_seconds=30.0,
        instance_results=results,
    )
    assert run.passed == 1
    assert run.failed == 1
    assert run.total == 2
    assert run.total_input_tokens == 300
    assert run.total_cost_usd == pytest.approx(1.5)
    assert run.total_cost_credits == pytest.approx(3.75)
    dump = run.model_dump()
    assert dump["checks_tests_passed"] == 1
    assert dump["checks_tests_failed"] == 1
    assert dump["checks_tests_total"] == 2
