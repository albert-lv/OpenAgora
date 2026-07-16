"""Agent registry: maps short names to agent adapters."""

from __future__ import annotations

from typing import Type

from openagora_cli.agents.base import AgentContext, BaseAgent, ArenaMinimalAgent
from openagora_cli.agents.installed.claude_code import ClaudeCodeAgent
from openagora_cli.agents.installed.codex_cli import CodexCLIAgent
from openagora_cli.agents.installed.openhands import OpenHandsAgent


class AgentRegistry:
    """Registry of built-in and user-registered agents."""

    def __init__(self):
        self._agents: dict[str, Type[BaseAgent]] = {}
        self.register(ArenaMinimalAgent)
        self.register(ClaudeCodeAgent)
        self.register(CodexCLIAgent)
        self.register(OpenHandsAgent)

    def register(self, cls: Type[BaseAgent]) -> None:
        self._agents[cls.name] = cls

    def get(self, name: str) -> BaseAgent:
        cls = self._agents.get(name)
        if cls is None:
            raise KeyError(
                f"unknown agent {name!r}; registered: {list(self._agents.keys())}"
            )
        return cls()

    def list(self) -> list[str]:
        return sorted(self._agents.keys())


def default_registry() -> AgentRegistry:
    return AgentRegistry()


__all__ = [
    "AgentRegistry",
    "default_registry",
    "BaseAgent",
    "AgentContext",
    "ArenaMinimalAgent",
    "ClaudeCodeAgent",
    "CodexCLIAgent",
    "OpenHandsAgent",
]
