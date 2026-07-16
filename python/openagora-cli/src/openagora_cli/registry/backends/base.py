"""Dataset registry backend interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from openagora_cli.registry.models import DatasetSpec


class RegistryBackend(ABC):
    """Abstract backend for discovering and loading datasets."""

    name: str = ""

    @abstractmethod
    def list(self) -> list[DatasetSpec]:
        """Return all available datasets from this backend."""

    @abstractmethod
    def load(self, name: str, version: Optional[str] = None) -> Optional[DatasetSpec]:
        """Return a specific dataset spec, or None if not found."""
