"""OpenHands agent adapter.

Skeleton adapter for the OpenHands agent runtime. In a full implementation this
would either start the OpenHands runtime server inside the sandbox or shell out
to the `openhands` CLI.
"""

from __future__ import annotations

import os
from typing import Any, Optional

from openagora_cli.agents.base import BaseAgent
from openagora_cli.task.config import TaskConfig


class OpenHandsAgent(BaseAgent):
    """Built-in adapter for OpenHands.

    Expects one of `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, or the configured
    provider API key in the host environment.
    """

    name = "openhands"
    supported_skills = ["file_io", "bash", "browser", "mcp"]

    DEFAULT_IMAGE = "allhands/openhands:latest"

    def prepare_task(
        self, config: TaskConfig, instruction: str
    ) -> tuple[dict[str, Any], dict[str, str]]:
        env: dict[str, str] = {}
        for key in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "LLM_API_KEY"):
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
        # OpenHands can run headless via `python -m openhands.core.main`.
        # This is a minimal non-interactive entrypoint suitable for eval loops.
        return [
            "python",
            "-m",
            "openhands.core.main",
            "-t",
            instruction,
            "--no-use-microagent",
        ]
