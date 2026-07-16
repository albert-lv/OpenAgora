"""Plugin base class for Arena CLI observability hooks."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class Plugin(ABC):
    """Base class for Arena CLI plugins."""

    name: str = ""

    @abstractmethod
    def is_enabled(self) -> bool:
        """Return True if the plugin should be activated."""

    def on_job_start(self, job_context: dict[str, Any]) -> None:
        """Called once when `arena run` starts."""

    def on_rollout_start(self, rollout_id: str, context: dict[str, Any]) -> None:
        """Called before each rollout is created."""

    def on_rollout_end(self, rollout_id: str, result: dict[str, Any]) -> None:
        """Called after a rollout reaches a terminal state."""

    def on_job_end(self, job_context: dict[str, Any]) -> None:
        """Called once when `arena run` finishes."""
