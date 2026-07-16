"""Local filesystem registry backend (built-in datasets)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from openagora_cli.registry.backends.base import RegistryBackend
from openagora_cli.registry.models import DatasetSpec


class LocalBackend(RegistryBackend):
    """Reads datasets from a local JSON registry file."""

    name = "local"

    def __init__(self, path: Path):
        self._path = path

    def list(self) -> list[DatasetSpec]:
        if not self._path.exists():
            return []
        data = json.loads(self._path.read_text(encoding="utf-8"))
        return [DatasetSpec.model_validate(d) for d in data.get("datasets", [])]

    def load(self, name: str, version: Optional[str] = None) -> Optional[DatasetSpec]:
        for spec in self.list():
            if spec.name == name and (version is None or spec.version == version):
                return spec
        return None
