import re
from pathlib import Path

from pydantic import BaseModel, Field, field_validator, model_validator

_ENV_NAME_RE = re.compile(r"^[A-Z_][A-Z0-9_]*$")


def _validate_env_names(names: list[str]) -> list[str]:
    for name in names:
        if not _ENV_NAME_RE.match(name):
            raise ValueError(f"Invalid env var name: {name!r} (must match [A-Z_][A-Z0-9_]*)")
    return names


class HookConfig(BaseModel):
    command: str
    timeout_sec: int

    @field_validator("command")
    @classmethod
    def command_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("hook command must not be empty")
        return v

    @field_validator("timeout_sec")
    @classmethod
    def timeout_positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("timeout_sec must be a positive integer")
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
            raise ValueError("check command must not be empty")
        return v

    @field_validator("timeout_sec")
    @classmethod
    def timeout_positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("timeout_sec must be a positive integer")
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
            raise ValueError("docker image/dockerfile must not be empty")
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
            raise ValueError("docker.image and docker.dockerfile are mutually exclusive")
        return self

    def resolve_dockerfile_path(self, instance_dir: Path) -> Path | None:
        if not self.dockerfile:
            return None
        resolved = (instance_dir / self.dockerfile).resolve()
        instance_resolved = instance_dir.resolve()
        try:
            resolved.relative_to(instance_resolved)
        except ValueError:
            raise ValueError("docker.dockerfile must not escape instance directory") from None
        if not resolved.exists():
            raise ValueError(f"docker.dockerfile: file not found: {resolved}")
        return resolved


class InstanceConfig(BaseModel):
    instance_id: str
    repo: str
    base_commit: str
    instance_timeout_sec: int | None = None
    hooks: HooksConfig | None = None
    prepare_patch_path: str | None = None
    test_patch_path: str | None = None
    prompt: str
    docker: DockerConfig = Field(default_factory=DockerConfig)
    check_commands: list[CheckCommand]

    @field_validator("repo")
    @classmethod
    def repo_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("repo must not be empty")
        return v

    @field_validator("base_commit")
    @classmethod
    def base_commit_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("base_commit must not be empty")
        return v

    @field_validator("instance_timeout_sec")
    @classmethod
    def timeout_positive(cls, v: int | None) -> int | None:
        if v is not None and v <= 0:
            raise ValueError("instance_timeout_sec must be a positive integer")
        return v

    @model_validator(mode="after")
    def validate_check_commands(self) -> "InstanceConfig":
        if not self.check_commands:
            raise ValueError("check_commands must not be empty")
        names = [c.name for c in self.check_commands]
        if len(names) != len(set(names)):
            raise ValueError("check_commands names must be unique within instance")
        return self

    def resolve_patch_paths(self, instance_dir: Path) -> tuple[Path | None, Path | None]:
        """Resolve and validate patch paths relative to instance dir."""
        prepare = self._resolve_patch(self.prepare_patch_path, instance_dir, "prepare_patch_path")
        test = self._resolve_patch(self.test_patch_path, instance_dir, "test_patch_path")
        return prepare, test

    def _resolve_patch(self, rel_path: str | None, instance_dir: Path, field: str) -> Path | None:
        if not rel_path:
            return None
        resolved = (instance_dir / rel_path).resolve()
        instance_resolved = instance_dir.resolve()
        try:
            resolved.relative_to(instance_resolved)
        except ValueError:
            raise ValueError(f"{field} must not escape instance directory") from None
        if not resolved.exists():
            raise ValueError(f"{field}: file not found: {resolved}")
        return resolved
