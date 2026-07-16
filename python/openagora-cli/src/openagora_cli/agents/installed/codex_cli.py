"""Codex CLI agent adapter.

Runs OpenAI's `codex` CLI inside the sandbox with the task prompt.
"""

from __future__ import annotations

import os
from typing import Any, Optional

from openagora_cli.agents.base import BaseAgent
from openagora_cli.task.config import TaskConfig


class CodexCLIAgent(BaseAgent):
    """Built-in adapter for OpenAI Codex CLI.

    Expects `OPENAI_API_KEY` to be set in the host environment.
    """

    name = "codex-cli"
    supported_skills = ["file_io", "bash"]

    DEFAULT_IMAGE = "openai/codex-cli:latest"

    def prepare_task(
        self, config: TaskConfig, instruction: str
    ) -> tuple[dict[str, Any], dict[str, str]]:
        env: dict[str, str] = {}
        for key in ("OPENAI_API_KEY",):
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
        # -q / --quiet and -a / --approval-mode no-approval are best for eval loops.
        return [
            "codex",
            "-q",
            "-a",
            "no-approval",
            "-p",
            instruction,
        ]
