"""Claude Code agent adapter.

Runs Anthropic's `claude-code` CLI inside the sandbox with the task prompt.
"""

from __future__ import annotations

import os
from typing import Any, Optional

from openagora_cli.agents.base import BaseAgent
from openagora_cli.task.config import TaskConfig


class ClaudeCodeAgent(BaseAgent):
    """Built-in adapter for Anthropic Claude Code.

    Expects `ANTHROPIC_API_KEY` to be set in the host environment and forwards it
    to the sandbox.
    """

    name = "claude-code"
    supported_skills = ["file_io", "bash", "web_search", "mcp"]

    DEFAULT_IMAGE = "anthropic/claude-code:latest"

    def prepare_task(
        self, config: TaskConfig, instruction: str
    ) -> tuple[dict[str, Any], dict[str, str]]:
        env: dict[str, str] = {}
        for key in ("ANTHROPIC_API_KEY",):
            if os.environ.get(key):
                env[key] = os.environ[key]
        task = config.to_task_json(instruction)
        task["agent"] = {"name": self.name, "model": config.agent.model}
        return task, env

    def resolve_image(self, config: TaskConfig) -> str:
        return config.environment.image or self.DEFAULT_IMAGE

    def entrypoint(
        self,
        config: TaskConfig,
        task_json: dict[str, Any],
        instruction: str,
        env_vars: dict[str, str],
    ) -> Optional[list[str]]:
        # --dangerously-skip-permissions allows non-interactive usage.
        # -p / --prompt passes the instruction as a single prompt.
        return [
            "claude",
            "--dangerously-skip-permissions",
            "-p",
            instruction,
        ]
