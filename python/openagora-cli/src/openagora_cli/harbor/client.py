"""Async client wrapper around Harbor's registry client."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from openagora_cli.registry.models import DatasetSpec


class HarborClient:
    """Lightweight async client for the Harbor registry.

    Falls back gracefully when ``harbor`` is not installed.
    """

    def __init__(self):
        self._client: Optional[object] = None

    def _ensure_available(self) -> None:
        if self._client is None:
            try:
                from harbor.registry.client.factory import RegistryClientFactory
            except ImportError as exc:
                raise RuntimeError(
                    "Harbor integration requires 'harbor'. "
                    "Install with: uv pip install 'openagora-cli[harbor]'"
                ) from exc
            self._client = RegistryClientFactory().create()

    async def list_datasets(self) -> list[DatasetSpec]:
        """List public datasets from the Harbor registry."""
        self._ensure_available()
        items = await self._client.list_datasets()
        return [
            DatasetSpec(
                name=item.name,
                version=item.version,
                description=item.description or "",
            )
            for item in items
        ]

    async def import_dataset(
        self, name: str, version: str, target_dir: Path
    ) -> list[Path]:
        """Download a Harbor dataset into ``target_dir``.

        Returns the list of task directories that were downloaded.
        """
        self._ensure_available()
        target_dir.mkdir(parents=True, exist_ok=True)
        items = await self._client.download_dataset(name, version, target_dir)
        return [item.downloaded_path for item in items]
