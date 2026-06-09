from pathlib import Path

import pytest

from benchrail.runner.orchestrator import ConfigError, _discover_instances


def test_discover_instances_applies_dataset_config_defaults(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset"
    instance_dir = dataset / "task-1"
    instance_dir.mkdir(parents=True)

    (dataset / "config.json").write_text(
        """
        {
          "repo": "https://github.com/example/repo.git",
          "base_commit": "abc123",
          "prompt": "Fix the bug",
          "check_commands": [
            {"name": "tests", "command": "make test", "timeout_sec": 300}
          ],
          "docker": {
            "image": "benchrail-universal:latest",
            "env": {"COMMON": "1"}
          }
        }
        """.strip(),
        encoding="utf-8",
    )
    (instance_dir / "config.json").write_text(
        """
        {
          "instance_id": "task-1",
          "docker": {
            "env": {"INSTANCE": "1"}
          }
        }
        """.strip(),
        encoding="utf-8",
    )

    instances = _discover_instances(dataset)

    assert list(instances) == ["task-1"]
    config = instances["task-1"]
    assert config.repo == "https://github.com/example/repo.git"
    assert config.base_commit == "abc123"
    assert config.prompt == "Fix the bug"
    assert config.docker.image == "benchrail-universal:latest"
    assert config.docker.env == {"COMMON": "1", "INSTANCE": "1"}


def test_discover_instances_reports_invalid_dataset_config(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset"
    dataset.mkdir()
    (dataset / "config.json").write_text('{"check_commands": []}', encoding="utf-8")

    with pytest.raises(ConfigError, match=r"Invalid dataset config\.json"):
        _discover_instances(dataset)


def test_discover_instances_accepts_dataset_default_dockerfile(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset"
    instance_dir = dataset / "task-1"
    environment_dir = dataset / "environment"
    instance_dir.mkdir(parents=True)
    environment_dir.mkdir()
    (environment_dir / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")
    (dataset / "config.json").write_text(
        """
        {
          "repo": "https://github.com/example/repo.git",
          "base_commit": "abc123",
          "prompt": "Fix the bug",
          "docker": {"dockerfile": "environment/Dockerfile"},
          "check_commands": [
            {"name": "tests", "command": "make test", "timeout_sec": 300}
          ]
        }
        """.strip(),
        encoding="utf-8",
    )
    (instance_dir / "config.json").write_text('{"instance_id": "task-1"}', encoding="utf-8")

    instances = _discover_instances(dataset)

    assert instances["task-1"].docker.dockerfile == "environment/Dockerfile"
