import json
from pathlib import Path
from typing import ClassVar

from benchrail.adapters.base import AgentRunResult, BaseAdapter


def _as_dict(value: object) -> dict[str, object] | None:
    return value if isinstance(value, dict) else None


def _as_int(value: object) -> int | None:
    return value if isinstance(value, int) else None


def _as_float(value: object) -> float | None:
    return float(value) if isinstance(value, int | float) else None


def _as_str(value: object) -> str | None:
    return value if isinstance(value, str) else None


class ClaudeCodeAdapter(BaseAdapter):
    FIXED_ARGS: ClassVar[list[str]] = [
        "--print",
        "--output-format=json",
        "--no-session-persistence",
        "--dangerously-skip-permissions",
    ]

    def _base_command(self, execution_mode: str) -> list[str]:
        return ["claude", *self.FIXED_ARGS]

    def auth_session_file(self) -> Path | None:
        return Path.home() / ".claude" / ".credentials.json"

    def parse_result(
        self,
        stdout: bytes,
        stderr: bytes,
        exit_code: int,
        duration_ms: int,
    ) -> AgentRunResult:
        session_id = ""
        turns: int | None = None
        input_tokens: int | None = None
        output_tokens: int | None = None
        cache_read_tokens: int | None = None
        cache_creation_tokens: int | None = None
        cost_usd: float | None = None
        model: str | None = None

        try:
            text = stdout.decode("utf-8", errors="replace").strip()
            payload = json.loads(text)
            data = _as_dict(payload)
            if data is None:
                raise ValueError("Claude output must be a JSON object")

            session_id = _as_str(data.get("session_id")) or ""
            turns = _as_int(data.get("num_turns"))
            cost_usd = _as_float(data.get("total_cost_usd"))

            if "duration_ms" in data:
                parsed_duration_ms = _as_int(data["duration_ms"])
                if parsed_duration_ms is not None:
                    duration_ms = parsed_duration_ms

            usage = _as_dict(data.get("usage")) or {}
            input_tokens = _as_int(usage.get("input_tokens"))
            output_tokens = _as_int(usage.get("output_tokens"))
            cache_read_tokens = _as_int(usage.get("cache_read_input_tokens"))
            cache_creation_tokens = _as_int(usage.get("cache_creation_input_tokens"))

            model_usage = _as_dict(data.get("modelUsage")) or {}
            if model_usage:
                model = next(iter(model_usage.keys()), None)
        except Exception:
            pass

        return AgentRunResult(
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            duration_ms=duration_ms,
            agent_session_id=session_id,
            turns=turns,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_tokens=cache_read_tokens,
            cache_creation_tokens=cache_creation_tokens,
            cost_usd=cost_usd,
            model=model,
        )
