from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar


@dataclass
class AgentRunResult:
    exit_code: int
    stdout: bytes
    stderr: bytes
    duration_ms: int
    agent_session_id: str = ""
    turns: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cache_read_tokens: int | None = None
    cache_creation_tokens: int | None = None
    reasoning_tokens: int | None = None
    cost_usd: float | None = None
    cost_credits: float | None = None
    model: str | None = None


class BaseAdapter(ABC):
    FIXED_ARGS: ClassVar[list[str]] = []

    def __init__(self, extra_args: list[str] | None = None) -> None:
        self.extra_args: list[str] = extra_args or []

    def build_command(self, prompt: str, execution_mode: str = "local") -> list[str]:
        return self._base_command(execution_mode) + self.extra_args + [prompt]

    def auth_session_file(self) -> Path | None:
        return None

    @abstractmethod
    def _base_command(self, execution_mode: str) -> list[str]: ...

    @abstractmethod
    def parse_result(
        self,
        stdout: bytes,
        stderr: bytes,
        exit_code: int,
        duration_ms: int,
    ) -> AgentRunResult: ...
