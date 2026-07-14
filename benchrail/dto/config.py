import re
from copy import deepcopy
from pathlib import Path
from typing import Any, cast

from benchrail.pydantic_compat import BaseModel, Field, field_validator, model_validator

_ENV_NAME_RE = re.compile(r"^[A-Z_][A-Z0-9_]*$")


def _validate_env_names(names: list[str]) -> list[str]:
    for name in names:
        if not _ENV_NAME_RE.match(name):
            msg = f"Invalid env var name: {name!r} (must match [A-Z_][A-Z0-9_]*)"
            raise ValueError(msg)
    return names


class HookConfig(BaseModel):
    command: str
    timeout_sec: int

    @field_validator("command")
    @classmethod
    def command_not_empty(cls, v: str) -> str:
        if not v.strip():
            msg = "hook command must not be empty"
            raise ValueError(msg)
        return v

    @field_validator("timeout_sec")
    @classmethod
    def timeout_positive(cls, v: int) -> int:
        if v <= 0:
            msg = "timeout_sec must be a positive integer"
            raise ValueError(msg)
        return v


class HooksConfig(BaseModel):
    before_agent: HookConfig | None = None
    before_checks: HookConfig | None = None


class CheckCommand(BaseModel):
    name: str
    command: str
    timeout_sec: int

    @field_validator("command")
    @classmethod
    def command_not_empty(cls, v: str) -> str:
        if not v.strip():
            msg = "check command must not be empty"
            raise ValueError(msg)
        return v

    @field_validator("timeout_sec")
    @classmethod
    def timeout_positive(cls, v: int) -> int:
        if v <= 0:
            msg = "timeout_sec must be a positive integer"
            raise ValueError(msg)
        return v


class DockerConfig(BaseModel):
    image: str | None = None
    dockerfile: str | None = None
    env: dict[str, str] = Field(default_factory=dict)
    env_from_host: list[str] = Field(default_factory=list)

    @field_validator("image", "dockerfile")
    @classmethod
    def validate_optional_path_or_ref(cls, v: str | None) -> str | None:
        if v is not None and not v.strip():
            msg = "docker image/dockerfile must not be empty"
            raise ValueError(msg)
        return v

    @field_validator("env")
    @classmethod
    def validate_env_keys(cls, v: dict[str, str]) -> dict[str, str]:
        _validate_env_names(list(v.keys()))
        return v

    @field_validator("env_from_host")
    @classmethod
    def validate_env_from_host(cls, v: list[str]) -> list[str]:
        return _validate_env_names(v)

    @model_validator(mode="after")
    def validate_image_xor_dockerfile(self) -> "DockerConfig":
        if self.image and self.dockerfile:
            msg = "docker.image and docker.dockerfile are mutually exclusive"
            raise ValueError(msg)
        return self

    def resolve_dockerfile_path(
        self,
        instance_dir: Path,
        dataset_dir: Path | None = None,
    ) -> Path | None:
        if not self.dockerfile:
            return None

        roots = [instance_dir]
        if dataset_dir is not None:
            roots.append(dataset_dir)

        candidates: list[Path] = []
        for root in roots:
            resolved = (root / self.dockerfile).resolve()
            try:
                resolved.relative_to(root.resolve())
            except ValueError:
                msg = "docker.dockerfile must not escape its config directory"
                raise ValueError(msg) from None
            candidates.append(resolved)
            if resolved.exists():
                return resolved

        msg = f"docker.dockerfile: file not found: {', '.join(map(str, candidates))}"
        raise ValueError(msg)


class InstanceConfig(BaseModel):
    instance_id: str
    repo: str
    base_commit: str
    instance_timeout_sec: int | None = None
    hooks: HooksConfig | None = None
    prepare_patch_path: str | None = None
    test_patch_path: str | None = None
    expected_migration_json_path: str | None = None
    prompt: str
    docker: DockerConfig = Field(default_factory=DockerConfig)
    check_commands: list[CheckCommand]

    @field_validator("repo")
    @classmethod
    def repo_not_empty(cls, v: str) -> str:
        if not v.strip():
            msg = "repo must not be empty"
            raise ValueError(msg)
        return v

    @field_validator("base_commit")
    @classmethod
    def base_commit_not_empty(cls, v: str) -> str:
        if not v.strip():
            msg = "base_commit must not be empty"
            raise ValueError(msg)
        return v

    @field_validator("instance_timeout_sec")
    @classmethod
    def timeout_positive(cls, v: int | None) -> int | None:
        if v is not None and v <= 0:
            msg = "instance_timeout_sec must be a positive integer"
            raise ValueError(msg)
        return v

    @model_validator(mode="after")
    def validate_check_commands(self) -> "InstanceConfig":
        if not self.check_commands:
            msg = "check_commands must not be empty"
            raise ValueError(msg)
        names = [c.name for c in self.check_commands]
        if len(names) != len(set(names)):
            msg = "check_commands names must be unique within instance"
            raise ValueError(msg)
        return self

    def resolve_patch_paths(self, instance_dir: Path) -> tuple[Path | None, Path | None]:
        """Resolve and validate patch paths relative to instance dir."""
        prepare = self._resolve_instance_file(
            self.prepare_patch_path,
            instance_dir,
            "prepare_patch_path",
        )
        test = self._resolve_instance_file(
            self.test_patch_path,
            instance_dir,
            "test_patch_path",
        )
        return prepare, test

    def resolve_expected_migration_json_path(self, instance_dir: Path) -> Path | None:
        if self.expected_migration_json_path:
            return self._resolve_instance_file(
                self.expected_migration_json_path,
                instance_dir,
                "expected_migration_json_path",
            )
        default_path = instance_dir / "expected_migration.json"
        if default_path.exists():
            return default_path.resolve()
        return None

    def _resolve_instance_file(
        self,
        rel_path: str | None,
        instance_dir: Path,
        field: str,
    ) -> Path | None:
        if not rel_path:
            return None
        resolved = (instance_dir / rel_path).resolve()
        instance_resolved = instance_dir.resolve()
        try:
            resolved.relative_to(instance_resolved)
        except ValueError:
            msg = f"{field} must not escape instance directory"
            raise ValueError(msg) from None
        if not resolved.exists():
            msg = f"{field}: file not found: {resolved}"
            raise ValueError(msg)
        return resolved


class DatasetConfig(BaseModel):
    repo: str | None = None
    base_commit: str | None = None
    instance_timeout_sec: int | None = None
    hooks: HooksConfig | None = None
    prepare_patch_path: str | None = None
    test_patch_path: str | None = None
    expected_migration_json_path: str | None = None
    prompt: str | None = None
    docker: DockerConfig | None = None
    check_commands: list[CheckCommand] | None = None

    @field_validator("repo")
    @classmethod
    def repo_not_empty(cls, v: str | None) -> str | None:
        if v is not None and not v.strip():
            msg = "repo must not be empty"
            raise ValueError(msg)
        return v

    @field_validator("base_commit")
    @classmethod
    def base_commit_not_empty(cls, v: str | None) -> str | None:
        if v is not None and not v.strip():
            msg = "base_commit must not be empty"
            raise ValueError(msg)
        return v

    @field_validator("instance_timeout_sec")
    @classmethod
    def timeout_positive(cls, v: int | None) -> int | None:
        if v is not None and v <= 0:
            msg = "instance_timeout_sec must be a positive integer"
            raise ValueError(msg)
        return v

    @model_validator(mode="after")
    def validate_check_commands(self) -> "DatasetConfig":
        if self.check_commands is None:
            return self
        if not self.check_commands:
            msg = "check_commands must not be empty"
            raise ValueError(msg)
        names = [c.name for c in self.check_commands]
        if len(names) != len(set(names)):
            msg = "check_commands names must be unique within config"
            raise ValueError(msg)
        return self


def merge_dataset_config(
    dataset_config: DatasetConfig | None,
    instance_data: dict[str, object],
) -> dict[str, object]:
    base = dataset_config.model_dump(exclude_unset=True) if dataset_config is not None else {}
    return _merge_config_objects(base, instance_data)


def _merge_config_objects(base: dict[str, Any], override: dict[str, object]) -> dict[str, object]:
    merged: dict[str, object] = deepcopy(base)
    for key, value in override.items():
        if key == "hooks" and isinstance(merged.get(key), dict) and isinstance(value, dict):
            merged[key] = _merge_plain_dicts(cast("dict[str, Any]", merged[key]), value)
        elif key == "docker" and isinstance(merged.get(key), dict) and isinstance(value, dict):
            merged[key] = _merge_docker_dicts(cast("dict[str, Any]", merged[key]), value)
        elif (
            key == "check_commands"
            and isinstance(merged.get(key), list)
            and isinstance(value, list)
        ):
            merged[key] = _merge_check_commands(cast("list[object]", merged[key]), value)
        else:
            merged[key] = deepcopy(value)
    return merged


def _merge_plain_dicts(base: dict[str, Any], override: dict[str, object]) -> dict[str, object]:
    merged: dict[str, object] = deepcopy(base)
    for key, value in override.items():
        merged[key] = deepcopy(value)
    return merged


def _merge_docker_dicts(base: dict[str, Any], override: dict[str, object]) -> dict[str, object]:
    merged: dict[str, object] = deepcopy(base)
    if override.get("image"):
        merged.pop("dockerfile", None)
    if override.get("dockerfile"):
        merged.pop("image", None)
    for key, value in override.items():
        if key == "env" and isinstance(merged.get(key), dict) and isinstance(value, dict):
            merged[key] = _merge_plain_dicts(cast("dict[str, Any]", merged[key]), value)
        elif (
            key == "env_from_host" and isinstance(merged.get(key), list) and isinstance(value, list)
        ):
            merged[key] = _merge_unique_lists(cast("list[object]", merged[key]), value)
        else:
            merged[key] = deepcopy(value)
    return merged


def _merge_unique_lists(base: list[object], override: list[object]) -> list[object]:
    merged: list[object] = deepcopy(base)
    seen = set(base)
    for item in override:
        if item not in seen:
            merged.append(deepcopy(item))
            seen.add(item)
    return merged


def _merge_check_commands(base: list[object], override: list[object]) -> list[object]:
    merged: list[object] = deepcopy(base)
    positions = {
        item["name"]: index
        for index, item in enumerate(merged)
        if isinstance(item, dict) and isinstance(item.get("name"), str)
    }
    for item in override:
        if (
            isinstance(item, dict)
            and isinstance(item.get("name"), str)
            and item["name"] in positions
        ):
            merged[positions[item["name"]]] = deepcopy(item)
        else:
            merged.append(deepcopy(item))
    return merged
