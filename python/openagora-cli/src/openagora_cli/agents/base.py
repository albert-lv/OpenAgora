"""Agent adapter interface for Arena CLI."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional

from openagora_cli.task.config import TaskConfig


class AgentContext:
    """Runtime context passed to an agent adapter."""

    def __init__(
        self, rollout_id: str, task_dir: str | None = None, model: str | None = None
    ):
        self.rollout_id = rollout_id
        self.task_dir = task_dir
        self.model = model
        self.metadata: dict[str, Any] = {}


class BaseAgent(ABC):
    """Abstract agent adapter."""

    name: str = ""
    supported_skills: list[str] = []

    @abstractmethod
    def prepare_task(
        self,
        config: TaskConfig,
        instruction: str,
    ) -> tuple[dict[str, Any], dict[str, str]]:
        """Return (task_json_data, extra_env_vars) for the rollout."""

    @abstractmethod
    def resolve_image(self, config: TaskConfig) -> str:
        """Return the sandbox image to use for this agent."""

    def entrypoint(
        self,
        config: TaskConfig,
        task_json: dict[str, Any],
        instruction: str,
        env_vars: dict[str, str],
    ) -> Optional[list[str]]:
        """Optional override for the container/command entrypoint.

        Return None to use the image's default entrypoint.
        """
        return None

    def validate_skills(self, requested: list[str]) -> list[str]:
        """Return unsupported skills. Empty list means all requested are OK."""
        if not self.supported_skills:
            return []
        return [s for s in requested if s not in self.supported_skills]


class ArenaMinimalAgent(BaseAgent):
    """Built-in minimal agent adapter using OpenAgora's agent-minimal image."""

    name = "arena-minimal"
    supported_skills = ["file_io", "bash"]

    def prepare_task(
        self, config: TaskConfig, instruction: str
    ) -> tuple[dict[str, Any], dict[str, str]]:
        return config.to_task_json(instruction), {}

    def resolve_image(self, config: TaskConfig) -> str:
        return config.environment.image or "openagora-agent-minimal:latest"
