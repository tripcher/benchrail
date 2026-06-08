"""Tests for agent adapters."""

import json
from pathlib import Path

from benchrail.adapters.claude_code import ClaudeCodeAdapter
from benchrail.adapters.codex import CodexAdapter

# ─── ClaudeCodeAdapter ────────────────────────────────────────────────────────


def test_claude_build_command_no_extras() -> None:
    adapter = ClaudeCodeAdapter()
    cmd = adapter.build_command("Fix the bug")
    assert cmd[0] == "claude"
    assert "--print" in cmd
    assert "--output-format=json" in cmd
    assert "--dangerously-skip-permissions" in cmd
    assert cmd[-1] == "Fix the bug"


def test_claude_build_command_with_extras() -> None:
    adapter = ClaudeCodeAdapter(extra_args=["--model", "claude-sonnet-4-6"])
    cmd = adapter.build_command("prompt")
    assert "--model" in cmd
    assert "claude-sonnet-4-6" in cmd


def test_claude_auth_session_file_path() -> None:
    adapter = ClaudeCodeAdapter()
    assert adapter.auth_session_file() == Path.home() / ".claude" / ".credentials.json"


def test_claude_parse_result_valid_json() -> None:
    payload = {
        "type": "result",
        "session_id": "test-session-123",
        "num_turns": 5,
        "duration_ms": 12345,
        "usage": {
            "input_tokens": 1000,
            "output_tokens": 500,
            "cache_read_input_tokens": 200,
            "cache_creation_input_tokens": 100,
        },
        "total_cost_usd": 0.75,
        "modelUsage": {"claude-sonnet-4-6": {}},
    }
    stdout = json.dumps(payload).encode()
    adapter = ClaudeCodeAdapter()
    result = adapter.parse_result(stdout, b"", 0, 99999)

    assert result.agent_session_id == "test-session-123"
    assert result.turns == 5
    assert result.duration_ms == 12345
    assert result.input_tokens == 1000
    assert result.output_tokens == 500
    assert result.cache_read_tokens == 200
    assert result.cache_creation_tokens == 100
    assert result.cost_usd == 0.75
    assert result.cost_credits is None
    assert result.model == "claude-sonnet-4-6"


def test_claude_parse_result_invalid_json() -> None:
    adapter = ClaudeCodeAdapter()
    result = adapter.parse_result(b"not json", b"", 1, 5000)
    # Should not raise, just return defaults
    assert result.agent_session_id == ""
    assert result.turns is None
    assert result.duration_ms == 5000


# ─── CodexAdapter ─────────────────────────────────────────────────────────────


def test_codex_build_command() -> None:
    adapter = CodexAdapter(extra_args=["--model", "o4-mini"])
    cmd = adapter.build_command("Fix the bug")
    assert cmd[0] == "codex"
    assert "exec" in cmd
    assert "--json" in cmd
    assert "-c" in cmd
    assert "sandbox_workspace_write.network_access=true" in cmd
    assert 'approval_policy="never"' in cmd
    assert "--sandbox" in cmd
    assert "workspace-write" in cmd
    assert "--cd" in cmd
    assert "." in cmd
    assert "--model" in cmd
    assert "o4-mini" in cmd
    assert "--dangerously-bypass-approvals-and-sandbox" not in cmd
    assert cmd[-1] == "Fix the bug"


def test_codex_build_command_uses_danger_mode_in_docker() -> None:
    adapter = CodexAdapter(extra_args=["--model", "gpt-5.4"])
    cmd = adapter.build_command("Fix the bug", execution_mode="docker")

    assert cmd[0] == "codex"
    assert "--dangerously-bypass-approvals-and-sandbox" in cmd
    assert "--sandbox" not in cmd
    assert "--cd" not in cmd
    assert "workspace-write" not in cmd
    assert "sandbox_workspace_write.network_access=true" not in cmd
    assert 'approval_policy="never"' not in cmd
    assert cmd[-1] == "Fix the bug"


def test_codex_auth_session_file_path() -> None:
    adapter = CodexAdapter()
    assert adapter.auth_session_file() == Path.home() / ".codex" / "auth.json"


def test_codex_build_command_respects_explicit_permissions_flags() -> None:
    adapter = CodexAdapter(
        extra_args=[
            "--sandbox",
            "danger-full-access",
            "--cd",
            "/tmp/worktree",
            "-c",
            "sandbox_workspace_write.network_access=false",
            "-c",
            'approval_policy="on-request"',
        ]
    )
    cmd = adapter.build_command("prompt")

    assert cmd.count("-c") == 2
    assert "sandbox_workspace_write.network_access=true" not in cmd
    assert 'approval_policy="never"' not in cmd
    assert cmd.count("--sandbox") == 1
    assert "workspace-write" not in cmd
    assert cmd.count("--cd") == 1
    assert "." not in cmd


def test_codex_parse_result_jsonl() -> None:
    events = [
        {"type": "thread.started", "thread_id": "thread-abc-123"},
        {
            "type": "turn.completed",
            "usage": {
                "input_tokens": 500,
                "output_tokens": 200,
                "cached_input_tokens": 100,
                "reasoning_output_tokens": 0,
            },
        },
        {
            "type": "turn.completed",
            "usage": {
                "input_tokens": 300,
                "output_tokens": 150,
                "cached_input_tokens": 50,
                "reasoning_output_tokens": 0,
            },
        },
    ]
    stdout = b"\n".join(json.dumps(e).encode() for e in events)
    adapter = CodexAdapter(extra_args=["--model", "o4-mini"])
    result = adapter.parse_result(stdout, b"", 0, 10000)

    assert result.agent_session_id == "thread-abc-123"
    assert result.turns == 2
    assert result.input_tokens == 800
    assert result.output_tokens == 350
    assert result.cache_read_tokens == 150
    assert result.cost_usd == 0.002461
    assert result.cost_credits is None


def test_codex_extract_model_from_args() -> None:
    adapter = CodexAdapter(extra_args=["--model=o3"])
    model = adapter._extract_model()
    assert model == "o3"

    adapter2 = CodexAdapter(extra_args=["--model", "gpt-5.5"])
    model2 = adapter2._extract_model()
    assert model2 == "gpt-5.5"


def test_codex_parse_result_empty_output() -> None:
    adapter = CodexAdapter()
    result = adapter.parse_result(b"", b"", 1, 5000)
    assert result.agent_session_id == ""
    assert result.turns is None
