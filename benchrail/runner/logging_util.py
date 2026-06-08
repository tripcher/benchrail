"""Logging utilities: structured runner.log (logfmt) + console output."""

from __future__ import annotations

import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import IO, Protocol, cast

MAX_LOG_FILE_BYTES = 50 * 1024 * 1024  # 50 MB


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _logfmt_line(level: str, event: str, **kwargs: object) -> str:
    parts = [f"{_now_iso()} {level:<5} {event:<20}"]
    for k, v in kwargs.items():
        sv = str(v)
        if " " in sv or "=" in sv or '"' in sv:
            sv = f'"{sv}"'
        parts.append(f"{k}={sv}")
    return " ".join(parts)


class _RichConsole(Protocol):
    def print(self, *objects: object, **kwargs: object) -> None: ...


class RunnerLogger:
    """Writes structured logfmt lines to a runner.log file."""

    def __init__(self, log_path: Path) -> None:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        self._path = log_path
        self._file: IO[str] = open(log_path, "a", encoding="utf-8")  # noqa: SIM115
        self._lock = threading.Lock()

    def _write(self, level: str, event: str, **kwargs: object) -> None:
        line = _logfmt_line(level, event, **kwargs) + "\n"
        with self._lock:
            self._file.write(line)
            self._file.flush()

    def info(self, event: str, **kwargs: object) -> None:
        self._write("INFO", event, **kwargs)

    def warn(self, event: str, **kwargs: object) -> None:
        self._write("WARN", event, **kwargs)

    def error(self, event: str, **kwargs: object) -> None:
        self._write("ERROR", event, **kwargs)

    def debug(self, event: str, **kwargs: object) -> None:
        self._write("DEBUG", event, **kwargs)

    def close(self) -> None:
        with self._lock:
            self._file.close()


class TruncatingWriter:
    """Streams bytes to a file, truncating at max_bytes and appending a marker."""

    def __init__(
        self,
        path: Path,
        logger: RunnerLogger,
        max_bytes: int = MAX_LOG_FILE_BYTES,
    ) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._path = path
        self._logger = logger
        self._max_bytes = max_bytes
        self._written = 0
        self._omitted = 0
        self._truncated = False
        self._file = open(path, "wb")  # noqa: SIM115

    def write(self, data: bytes) -> None:
        if self._truncated:
            self._omitted += len(data)
            return
        remaining = self._max_bytes - self._written
        if len(data) <= remaining:
            self._file.write(data)
            self._written += len(data)
        else:
            if remaining > 0:
                self._file.write(data[:remaining])
                self._written += remaining
            self._omitted = len(data) - remaining
            self._truncated = True

    def close(self) -> None:
        if self._truncated:
            marker = f"\n[TRUNCATED: {self._omitted} bytes omitted]\n".encode()
            self._file.write(marker)
            self._file.flush()
            self._logger.warn(
                "LOG_TRUNCATED",
                file=self._path.name,
                limit_bytes=self._max_bytes,
            )
        self._file.close()


class ConsoleOutput:
    """CI (non-TTY) or interactive (TTY) console output."""

    def __init__(self) -> None:
        self._is_tty = sys.stdout.isatty()
        self._lock = threading.Lock()
        self._rich: _RichConsole | None = None

        if self._is_tty:
            try:
                from rich.console import Console

                self._rich = cast(_RichConsole, Console(stderr=False))
            except ImportError:
                self._is_tty = False

    @property
    def is_tty(self) -> bool:
        return self._is_tty

    def _ts(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def print(self, msg: str) -> None:
        with self._lock:
            if self._is_tty and self._rich is not None:
                self._rich.print(msg)
            else:
                print(msg, flush=True)

    def run_start(
        self,
        run_id: str,
        mode: str,
        dataset: str,
        tasks: int,
        workers: int,
    ) -> None:
        self.print(
            f"[{self._ts()}] RUN_START   run_id={run_id} mode={mode}"
            f" dataset={dataset} tasks={tasks} workers={workers}"
        )

    def task_start(self, instance: str, agent: str) -> None:
        self.print(f"[{self._ts()}] TASK_START  instance={instance} agent={agent}")

    def task_end(
        self,
        instance: str,
        agent: str,
        status: str,
        duration: float,
        turns: int | None = None,
        input_tokens: int | None = None,
        cost_usd: float | None = None,
        cost_credits: float | None = None,
        fail_step: str | None = None,
        fail_exit_code: int | None = None,
    ) -> None:
        parts = [
            f"[{self._ts()}] TASK_END    instance={instance} agent={agent}",
            f"status={status}",
            f"duration={duration:.1f}s",
        ]
        if turns is not None:
            parts.append(f"turns={turns}")
        if input_tokens is not None:
            parts.append(f"input_tokens={input_tokens}")
        if cost_usd is not None:
            parts.append(f"cost_usd={cost_usd:.4f}")
        if cost_credits is not None:
            parts.append(f"cost_credits={cost_credits:.4f}")
        if status == "fail" and fail_step:
            parts.append(f"step={fail_step}")
        if fail_exit_code is not None:
            parts.append(f"exit_code={fail_exit_code}")
        self.print(" ".join(parts))

    def run_end(
        self,
        status: str,
        passed: int,
        failed: int,
        total: int,
        duration: float,
        cost_usd: float | None = None,
        cost_credits: float | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
    ) -> None:
        parts = [
            f"[{self._ts()}] RUN_END     status={status}",
            f"passed={passed}",
            f"failed={failed}",
            f"total={total}",
            f"duration={duration:.1f}s",
        ]
        if cost_usd is not None:
            parts.append(f"cost_usd={cost_usd:.4f}")
        if cost_credits is not None:
            parts.append(f"cost_credits={cost_credits:.4f}")
        if input_tokens is not None:
            parts.append(f"input_tokens={input_tokens}")
        if output_tokens is not None:
            parts.append(f"output_tokens={output_tokens}")
        self.print(" ".join(parts))

    def print_summary(
        self,
        passed: int,
        failed: int,
        total: int,
        failed_tasks: list[tuple[str, str, str]],
        cost_usd: float | None,
        cost_credits: float | None,
        input_tokens: int | None,
        output_tokens: int | None,
        cache_read_tokens: int | None,
        total_time: float,
        agent_time: int | None,
    ) -> None:
        pct = int(passed / total * 100) if total else 0
        lines = [
            "",
            "Results:",
            f"  pass  {passed}/{total} ({pct}%)",
            f"  fail  {failed}/{total} ({100 - pct}%)",
        ]
        if failed_tasks:
            lines.append("")
            lines.append("  Failed tasks:")
            for inst, ag, reason in failed_tasks:
                lines.append(f"    {inst} / {ag}  ← {reason}")
        if cost_usd is not None or cost_credits is not None:
            if cost_usd is not None:
                lines.append(f"\n  Total cost:    ${cost_usd:.2f}")
            else:
                lines.append("\n  Total cost:")
            if cost_credits is not None:
                lines.append(f"                 {cost_credits:.4f} credits")
        tok_parts = []
        if input_tokens:
            tok_parts.append(f"{input_tokens:,} in")
        if output_tokens:
            tok_parts.append(f"{output_tokens:,} out")
        if cache_read_tokens:
            tok_parts.append(f"{cache_read_tokens:,} cache_read")
        if tok_parts:
            lines.append(f"  Total tokens:  {' / '.join(tok_parts)}")
        agent_sec = (agent_time // 1000) if agent_time else None
        lines.append(
            f"  Total time:    {total_time:.1f}s wall"
            + (f" / {agent_sec}s agent" if agent_sec else "")
        )
        self.print("\n".join(lines))
