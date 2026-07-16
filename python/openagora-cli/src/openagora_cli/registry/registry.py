"""Dataset registry manager that aggregates multiple backends."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from openagora_cli.registry.backends.base import RegistryBackend
from openagora_cli.registry.backends.local import LocalBackend
from openagora_cli.registry.backends.url import URLBackend
from openagora_cli.registry.backends.github import GitHubBackend
from openagora_cli.registry.models import DatasetSpec


def _harbor_backend() -> Optional[RegistryBackend]:
    """Return Harbor backend when the integration is enabled/available."""
    if os.environ.get("ARENA_HARBOR") not in ("1", "true", "yes"):
        return None
    try:
        from openagora_cli.harbor.backend import HarborRegistryBackend

        return HarborRegistryBackend()
    except Exception:
        return None


class DatasetRegistry:
    """Aggregates local, URL, and GitHub registry backends."""

    def __init__(self, backends: list[RegistryBackend]):
        self._backends = backends

    def list(self) -> list[DatasetSpec]:
        specs: list[DatasetSpec] = []
        seen: set[str] = set()
        for backend in self._backends:
            try:
                for spec in backend.list():
                    key = f"{spec.name}@{spec.version}"
                    if key not in seen:
                        seen.add(key)
                        specs.append(spec)
            except Exception as exc:
                print(f"[registry] warning: backend {backend.name} failed: {exc}")
        return specs

    def load(self, name: str, version: Optional[str] = None) -> Optional[DatasetSpec]:
        for backend in self._backends:
            try:
                spec = backend.load(name, version)
                if spec is not None:
                    return spec
            except Exception as exc:
                print(f"[registry] warning: backend {backend.name} failed: {exc}")
        return None


def default_registry() -> DatasetRegistry:
    """Build the default registry from environment variables and builtin file."""
    backends: list[RegistryBackend] = []

    # Built-in local registry.
    builtin_path = Path(__file__).parent / "builtin.json"
    backends.append(LocalBackend(builtin_path))

    # Optional user registry file.
    user_registry = os.environ.get("ARENA_REGISTRY")
    if user_registry:
        backends.append(LocalBackend(Path(user_registry)))

    # Optional remote URL registry.
    registry_url = os.environ.get("ARENA_REGISTRY_URL")
    if registry_url:
        backends.append(URLBackend(registry_url))

    # Optional GitHub registry.
    registry_github = os.environ.get("ARENA_REGISTRY_GITHUB")
    if registry_github:
        backends.append(GitHubBackend(registry_github))

    # Optional Harbor registry integration.
    harbor_backend = _harbor_backend()
    if harbor_backend is not None:
        backends.append(harbor_backend)

    return DatasetRegistry(backends)
