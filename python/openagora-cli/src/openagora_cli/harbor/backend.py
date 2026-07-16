"""Registry backend that discovers datasets from the Harbor registry."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from openagora_cli.harbor.client import HarborClient
from openagora_cli.registry.backends.base import RegistryBackend
from openagora_cli.registry.models import DatasetSpec


class HarborRegistryBackend(RegistryBackend):
    """Registry backend backed by the public Harbor registry."""

    name = "harbor"

    def __init__(self, cache_dir: Optional[Path] = None):
        self._client = HarborClient()
        self._cache_dir = cache_dir or Path.home() / ".arena" / "harbor"

    def list(self) -> list[DatasetSpec]:
        """Return Harbor datasets (best-effort; empty on network/auth errors)."""
        import asyncio

        try:
            return asyncio.run(self._client.list_datasets())
        except Exception:
            # Harbor registry may require auth or be unreachable.
            return []

    def load(self, name: str, version: Optional[str] = None) -> Optional[DatasetSpec]:
        """Import a Harbor dataset into the local Arena cache.

        ``name`` may include a version suffix (``name@version``).
        """
        import asyncio

        dataset_name, dataset_version = self._parse_name_version(name, version)
        if not dataset_version:
            return None

        target = self._cache_dir / f"{dataset_name}@{dataset_version}"
        try:
            task_dirs = asyncio.run(
                self._client.import_dataset(dataset_name, dataset_version, target)
            )
        except Exception:
            return None

        return DatasetSpec(
            name=dataset_name,
            version=dataset_version,
            description=f"Harbor dataset {dataset_name}@{dataset_version}",
            task_dir=str(target),
            task_ids=[str(p.name) for p in task_dirs],
        )

    @staticmethod
    def _parse_name_version(
        name: str, version: Optional[str]
    ) -> tuple[str, Optional[str]]:
        if "@" in name:
            n, v = name.split("@", 1)
            return n, v
        return name, version
