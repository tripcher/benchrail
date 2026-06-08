import json
from pathlib import Path
from typing import ClassVar

from benchrail.adapters.base import AgentRunResult, BaseAdapter
from benchrail.pricing import calc_codex_cost, calc_codex_credits


def _as_dict(value: object) -> dict[str, object] | None:
    return value if isinstance(value, dict) else None


def _as_int(value: object, default: int = 0) -> int:
    return value if isinstance(value, int) else default


def _as_str(value: object, default: str = "") -> str:
    return value if isinstance(value, str) else default


class CodexAdapter(BaseAdapter):
    FIXED_ARGS: ClassVar[list[str]] = [
        "exec",
        "--json",
        "--ephemeral",
    ]

    def _base_command(self, execution_mode: str) -> list[str]:
        args = ["codex", *self.FIXED_ARGS]

        if execution_mode == "docker":
            if not self._has_flag("--dangerously-bypass-approvals-and-sandbox"):
                args.append("--dangerously-bypass-approvals-and-sandbox")
            return args

        if not self._has_flag("--dangerously-bypass-approvals-and-sandbox"):
            if not self._has_config_override("sandbox_workspace_write.network_access"):
                args.extend(["-c", "sandbox_workspace_write.network_access=true"])
            if not self._has_config_override("approval_policy"):
                args.extend(["-c", 'approval_policy="never"'])
            if not self._has_flag("--sandbox"):
                args.extend(["--sandbox", "workspace-write"])
            if not self._has_flag("--cd"):
                args.extend(["--cd", "."])

        return args

    def _has_flag(self, name: str) -> bool:
        return any(arg == name or arg.startswith(f"{name}=") for arg in self.extra_args)

    def _has_config_override(self, key: str) -> bool:
        for i, arg in enumerate(self.extra_args):
            if (
                arg in {"-c", "--config"}
                and i + 1 < len(self.extra_args)
                and self.extra_args[i + 1].startswith(f"{key}=")
            ):
                return True
            if arg.startswith("--config="):
                _, _, value = arg.partition("=")
                if value.startswith(f"{key}="):
                    return True
        return False

    def _extract_model(self) -> str | None:
        for i, arg in enumerate(self.extra_args):
            if arg == "--model" and i + 1 < len(self.extra_args):
                return self.extra_args[i + 1]
            if arg.startswith("--model="):
                return arg[len("--model=") :]
        return None

    def auth_session_file(self) -> Path | None:
        return Path.home() / ".codex" / "auth.json"

    def parse_result(
        self,
        stdout: bytes,
        stderr: bytes,
        exit_code: int,
        duration_ms: int,
    ) -> AgentRunResult:
        session_id = ""
        turns = 0
        input_tokens = 0
        output_tokens = 0
        cache_read_tokens = 0
        reasoning_tokens = 0
        model = self._extract_model()

        try:
            text = stdout.decode("utf-8", errors="replace")
            for line in text.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    continue
                event = _as_dict(payload)
                if event is None:
                    continue

                etype = _as_str(event.get("type"))
                if etype == "thread.started":
                    session_id = _as_str(event.get("thread_id"))
                elif etype == "turn.completed":
                    turns += 1
                    usage = _as_dict(event.get("usage")) or {}
                    input_tokens += _as_int(usage.get("input_tokens"))
                    output_tokens += _as_int(usage.get("output_tokens"))
                    cache_read_tokens += _as_int(usage.get("cached_input_tokens"))
                    reasoning_tokens += _as_int(usage.get("reasoning_output_tokens"))
        except Exception:
            pass

        cost_usd: float | None = None
        cost_credits: float | None = None
        if model:
            cost_usd = calc_codex_cost(model, input_tokens, output_tokens, cache_read_tokens)
            cost_credits = calc_codex_credits(model, input_tokens, output_tokens, cache_read_tokens)

        return AgentRunResult(
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            duration_ms=duration_ms,
            agent_session_id=session_id,
            turns=turns if turns > 0 else None,
            input_tokens=input_tokens if input_tokens > 0 else None,
            output_tokens=output_tokens if output_tokens > 0 else None,
            cache_read_tokens=cache_read_tokens if cache_read_tokens > 0 else None,
            reasoning_tokens=reasoning_tokens if reasoning_tokens > 0 else None,
            cost_usd=cost_usd,
            cost_credits=cost_credits,
            model=model,
        )
