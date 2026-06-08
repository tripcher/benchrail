import shlex
from typing import TypedDict

from benchrail.adapters.base import BaseAdapter
from benchrail.adapters.claude_code import ClaudeCodeAdapter
from benchrail.adapters.codex import CodexAdapter


class AgentRegistryEntry(TypedDict):
    adapter: type[BaseAdapter]
    default_extra_args: list[str]


AGENT_REGISTRY: dict[str, AgentRegistryEntry] = {
    "claude-code": {
        "adapter": ClaudeCodeAdapter,
        "default_extra_args": [],
    },
    "codex": {
        "adapter": CodexAdapter,
        "default_extra_args": [],
    },
}


def build_adapter(
    agent_type: str, command: str | None, default_extra_args: list[str]
) -> BaseAdapter:
    """Instantiate an adapter from registry for the given agent type."""
    entry = AGENT_REGISTRY[agent_type]
    adapter_cls: type[BaseAdapter] = entry["adapter"]

    if command:
        extra_args = shlex.split(command)
    elif default_extra_args:
        extra_args = list(default_extra_args)
    else:
        extra_args = list(entry["default_extra_args"])

    return adapter_cls(extra_args=extra_args)
