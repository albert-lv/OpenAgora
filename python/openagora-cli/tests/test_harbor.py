"""Tests for the Harbor registry integration.

These tests mock the upstream ``harbor`` client so they can run without the
optional dependency installed.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from openagora_cli.harbor.backend import HarborRegistryBackend


class _FakeHarborClient:
    """Stand-in for ``harbor.registry.client.factory.RegistryClientFactory`` result."""

    def __init__(self, datasets=None, downloads=None):
        self._datasets = datasets or []
        self._downloads = downloads or {}

    async def list_datasets(self):
        return [
            SimpleNamespace(
                name=d["name"], version=d["version"], description=d.get("description")
            )
            for d in self._datasets
        ]

    async def download_dataset(self, name: str, version: str, target_dir: Path):
        key = f"{name}@{version}"
        task_names = self._downloads.get(key, [])
        result = []
        for task_name in task_names:
            task_dir = target_dir / task_name
            task_dir.mkdir(parents=True, exist_ok=True)
            (task_dir / "task.toml").write_text("[task]\n", encoding="utf-8")
            result.append(SimpleNamespace(downloaded_path=task_dir))
        return result


def _patch_client(monkeypatch, client):
    """Replace ``HarborClient._ensure_available`` to return the fake client."""
    from openagora_cli.harbor import client as client_mod

    def _fake_ensure_available(self):
        self._client = client

    monkeypatch.setattr(
        client_mod.HarborClient, "_ensure_available", _fake_ensure_available
    )


def test_backend_list_datasets(monkeypatch, tmp_path: Path):
    fake = _FakeHarborClient(
        datasets=[
            {"name": "swe-bench", "version": "1.0.0", "description": "SWE-bench"},
        ]
    )
    _patch_client(monkeypatch, fake)
    backend = HarborRegistryBackend(cache_dir=tmp_path)
    specs = backend.list()
    assert len(specs) == 1
    assert specs[0].name == "swe-bench"
    assert specs[0].version == "1.0.0"


def test_backend_load_dataset(monkeypatch, tmp_path: Path):
    fake = _FakeHarborClient(downloads={"swe-bench@1.0.0": ["task-1", "task-2"]})
    _patch_client(monkeypatch, fake)
    backend = HarborRegistryBackend(cache_dir=tmp_path)
    spec = backend.load("swe-bench@1.0.0")
    assert spec is not None
    assert spec.name == "swe-bench"
    assert spec.version == "1.0.0"
    assert set(spec.task_ids) == {"task-1", "task-2"}
    assert Path(spec.task_dir).exists()


def test_backend_load_without_version(monkeypatch, tmp_path: Path):
    """Loading without a version should gracefully return None."""
    fake = _FakeHarborClient()
    _patch_client(monkeypatch, fake)
    backend = HarborRegistryBackend(cache_dir=tmp_path)
    assert backend.load("swe-bench") is None


def test_backend_list_ignores_network_errors(monkeypatch, tmp_path: Path):
    """The backend should not crash when the Harbor registry is unreachable."""
    from openagora_cli.harbor import client as client_mod

    def _explode(self):
        raise RuntimeError("network down")

    monkeypatch.setattr(client_mod.HarborClient, "_ensure_available", _explode)
    backend = HarborRegistryBackend(cache_dir=tmp_path)
    assert backend.list() == []


def test_backend_load_ignores_network_errors(monkeypatch, tmp_path: Path):
    from openagora_cli.harbor import client as client_mod

    def _explode(self):
        raise RuntimeError("network down")

    monkeypatch.setattr(client_mod.HarborClient, "_ensure_available", _explode)
    backend = HarborRegistryBackend(cache_dir=tmp_path)
    assert backend.load("swe-bench@1.0.0") is None


def test_default_registry_honors_env_var(monkeypatch):
    """Harbor backend is included only when ARENA_HARBOR is enabled."""
    from openagora_cli.registry.registry import default_registry

    monkeypatch.delenv("ARENA_HARBOR", raising=False)
    registry_without = default_registry()
    names_without = {b.name for b in registry_without._backends}

    monkeypatch.setenv("ARENA_HARBOR", "1")
    # Guard the import in case ``harbor`` is not installed.
    try:
        registry_with = default_registry()
    except Exception:  # pragma: no cover - harbor not installed
        pytest.skip("harbor package not installed")
    names_with = {b.name for b in registry_with._backends}

    assert "harbor" not in names_without
    assert "harbor" in names_with
