"""URL-based registry backend."""

from __future__ import annotations

import json
from typing import Optional
from urllib.request import urlopen
from urllib.error import URLError

from openagora_cli.registry.backends.base import RegistryBackend
from openagora_cli.registry.models import DatasetSpec


class URLBackend(RegistryBackend):
    """Fetches a dataset registry JSON from a remote URL."""

    name = "url"

    def __init__(self, url: str):
        self._url = url

    def _fetch(self) -> dict:
        try:
            with urlopen(self._url, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (URLError, json.JSONDecodeError) as exc:
            raise RuntimeError(
                f"failed to fetch registry from {self._url}: {exc}"
            ) from exc

    def list(self) -> list[DatasetSpec]:
        data = self._fetch()
        return [DatasetSpec.model_validate(d) for d in data.get("datasets", [])]

    def load(self, name: str, version: Optional[str] = None) -> Optional[DatasetSpec]:
        for spec in self.list():
            if spec.name == name and (version is None or spec.version == version):
                return spec
        return None
