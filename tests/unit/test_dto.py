"""Tests for DTO models."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from benchrail.dto.config import (
    CheckCommand,
    DatasetConfig,
    InstanceConfig,
    merge_dataset_config,
)
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


def test_instance_config_nested_validation_does_not_add_root_error() -> None:
    data = {
        "instance_id": "task-1",
        "repo": "https://github.com/example/repo.git",
        "base_commit": "abc123",
        "prompt": "Fix the bug",
        "check_commands": [{"name": "tests", "command": "", "timeout_sec": 300}],
    }
    with pytest.raises(ValidationError) as exc_info:
        InstanceConfig.model_validate(data)

    assert all("__root__" not in error["loc"] for error in exc_info.value.errors())


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


def test_instance_config_resolve_expected_migration_json_path_missing(tmp_path: Path) -> None:
    data = {
        "instance_id": "task-1",
        "repo": "https://github.com/example/repo.git",
        "base_commit": "abc123",
        "prompt": "Fix",
        "check_commands": [{"name": "tests", "command": "make test", "timeout_sec": 60}],
        "expected_migration_json_path": "expected/migration.json",
    }
    c = InstanceConfig.model_validate(data)
    with pytest.raises(ValueError, match="file not found"):
        c.resolve_expected_migration_json_path(tmp_path)


def test_instance_config_resolve_expected_migration_json_path_escape(tmp_path: Path) -> None:
    data = {
        "instance_id": "task-1",
        "repo": "https://github.com/example/repo.git",
        "base_commit": "abc123",
        "prompt": "Fix",
        "check_commands": [{"name": "tests", "command": "make test", "timeout_sec": 60}],
        "expected_migration_json_path": "../../migration.json",
    }
    c = InstanceConfig.model_validate(data)
    with pytest.raises(ValueError, match="escape"):
        c.resolve_expected_migration_json_path(tmp_path)


def test_instance_config_resolve_expected_migration_json_path_uses_default_file(
    tmp_path: Path,
) -> None:
    default_path = tmp_path / "expected_migration.json"
    default_path.write_text('{"version": 1}\n', encoding="utf-8")
    data = {
        "instance_id": "task-1",
        "repo": "https://github.com/example/repo.git",
        "base_commit": "abc123",
        "prompt": "Fix",
        "check_commands": [{"name": "tests", "command": "make test", "timeout_sec": 60}],
    }
    c = InstanceConfig.model_validate(data)

    assert c.resolve_expected_migration_json_path(tmp_path) == default_path.resolve()


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


def test_instance_config_resolve_dockerfile_prefers_instance_over_dataset(tmp_path: Path) -> None:
    dataset_dir = tmp_path / "dataset"
    instance_dir = dataset_dir / "task-1"
    dataset_dockerfile = dataset_dir / "environment" / "Dockerfile"
    instance_dockerfile = instance_dir / "environment" / "Dockerfile"
    dataset_dockerfile.parent.mkdir(parents=True)
    instance_dockerfile.parent.mkdir(parents=True)
    dataset_dockerfile.write_text("FROM dataset\n", encoding="utf-8")
    instance_dockerfile.write_text("FROM instance\n", encoding="utf-8")
    config = InstanceConfig.model_validate(
        {
            "instance_id": "task-1",
            "repo": "https://github.com/example/repo.git",
            "base_commit": "abc123",
            "prompt": "Fix",
            "docker": {"dockerfile": "environment/Dockerfile"},
            "check_commands": [{"name": "tests", "command": "make test", "timeout_sec": 60}],
        }
    )

    assert config.docker.resolve_dockerfile_path(instance_dir, dataset_dir) == instance_dockerfile


def test_instance_config_resolve_dockerfile_falls_back_to_dataset(tmp_path: Path) -> None:
    dataset_dir = tmp_path / "dataset"
    instance_dir = dataset_dir / "task-1"
    dataset_dockerfile = dataset_dir / "environment" / "Dockerfile"
    dataset_dockerfile.parent.mkdir(parents=True)
    instance_dir.mkdir()
    dataset_dockerfile.write_text("FROM dataset\n", encoding="utf-8")
    config = InstanceConfig.model_validate(
        {
            "instance_id": "task-1",
            "repo": "https://github.com/example/repo.git",
            "base_commit": "abc123",
            "prompt": "Fix",
            "docker": {"dockerfile": "environment/Dockerfile"},
            "check_commands": [{"name": "tests", "command": "make test", "timeout_sec": 60}],
        }
    )

    assert config.docker.resolve_dockerfile_path(instance_dir, dataset_dir) == dataset_dockerfile


def test_dataset_config_valid() -> None:
    data = {
        "instance_timeout_sec": 3600,
        "hooks": {
            "before_agent": {
                "command": "sh setup.sh",
                "timeout_sec": 1800,
            }
        },
        "docker": {
            "image": "benchrail-universal:latest",
            "env_from_host": ["CODEX_API_KEY"],
        },
        "check_commands": [{"name": "tests", "command": "make test", "timeout_sec": 300}],
    }
    c = DatasetConfig.model_validate(data)
    assert c.instance_timeout_sec == 3600
    assert c.docker is not None
    assert c.docker.image == "benchrail-universal:latest"


def test_merge_dataset_config_merges_nested_fields() -> None:
    dataset_config = DatasetConfig.model_validate(
        {
            "repo": "https://github.com/example/repo.git",
            "base_commit": "abc123",
            "instance_timeout_sec": 3600,
            "hooks": {
                "before_agent": {
                    "command": "sh setup.sh",
                    "timeout_sec": 1800,
                }
            },
            "docker": {
                "image": "benchrail-universal:latest",
                "env": {"COMMON": "1"},
                "env_from_host": ["CODEX_API_KEY"],
            },
            "check_commands": [
                {"name": "gold_tests", "command": "make gold", "timeout_sec": 300},
                {"name": "project_tests", "command": "make test", "timeout_sec": 300},
            ],
        }
    )

    merged = merge_dataset_config(
        dataset_config,
        {
            "instance_id": "task-1",
            "prompt": "Fix the bug",
            "hooks": {
                "before_checks": {
                    "command": "sh verify.sh",
                    "timeout_sec": 120,
                }
            },
            "docker": {
                "env": {"INSTANCE": "1"},
                "env_from_host": ["OPENAI_API_KEY", "CODEX_API_KEY"],
            },
            "check_commands": [
                {"name": "project_tests", "command": "pytest -q", "timeout_sec": 600},
                {"name": "lint", "command": "ruff check .", "timeout_sec": 60},
            ],
        },
    )

    config = InstanceConfig.model_validate(merged)
    assert config.repo == "https://github.com/example/repo.git"
    assert config.base_commit == "abc123"
    assert config.instance_timeout_sec == 3600
    assert config.prompt == "Fix the bug"
    assert config.hooks is not None
    assert config.hooks.before_agent is not None
    assert config.hooks.before_checks is not None
    assert config.docker.env == {"COMMON": "1", "INSTANCE": "1"}
    assert config.docker.env_from_host == ["CODEX_API_KEY", "OPENAI_API_KEY"]
    assert [command.name for command in config.check_commands] == [
        "gold_tests",
        "project_tests",
        "lint",
    ]
    assert config.check_commands[1].command == "pytest -q"


def test_merge_dataset_config_allows_instance_override_of_scalar_fields() -> None:
    dataset_config = DatasetConfig.model_validate(
        {
            "repo": "https://github.com/example/repo.git",
            "base_commit": "abc123",
            "prompt": "Base prompt",
            "check_commands": [{"name": "tests", "command": "make test", "timeout_sec": 300}],
        }
    )

    merged = merge_dataset_config(
        dataset_config,
        {
            "instance_id": "task-1",
            "repo": "https://github.com/example/other.git",
            "prompt": "Instance prompt",
        },
    )

    config = InstanceConfig.model_validate(merged)
    assert config.repo == "https://github.com/example/other.git"
    assert config.prompt == "Instance prompt"
    assert config.base_commit == "abc123"


@pytest.mark.parametrize(
    ("dataset_docker", "instance_docker", "expected_image", "expected_dockerfile"),
    [
        (
            {"image": "default:latest"},
            {"dockerfile": "environment/Dockerfile"},
            None,
            "environment/Dockerfile",
        ),
        (
            {"dockerfile": "environment/Dockerfile"},
            {"image": "instance:latest"},
            "instance:latest",
            None,
        ),
    ],
)
def test_merge_dataset_config_instance_docker_strategy_overrides_default(
    dataset_docker: dict[str, str],
    instance_docker: dict[str, str],
    expected_image: str | None,
    expected_dockerfile: str | None,
) -> None:
    dataset_config = DatasetConfig.model_validate({"docker": dataset_docker})
    merged = merge_dataset_config(
        dataset_config,
        {
            "instance_id": "task-1",
            "repo": "https://github.com/example/repo.git",
            "base_commit": "abc123",
            "prompt": "Fix",
            "docker": instance_docker,
            "check_commands": [{"name": "tests", "command": "make test", "timeout_sec": 60}],
        },
    )

    config = InstanceConfig.model_validate(merged)
    assert config.docker.image == expected_image
    assert config.docker.dockerfile == expected_dockerfile


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


def test_run_result_model_validate_allows_extra_fields() -> None:
    run = RunResult.model_validate(
        {
            "run_id": "run-123",
            "mode": "local",
            "dataset_path": "dataset",
            "status": "completed",
            "passed": 1,
            "failed": 0,
            "total": 1,
            "duration_seconds": 30.0,
            "checks_tests_passed": 1,
        }
    )
    assert run.model_dump()["checks_tests_passed"] == 1
