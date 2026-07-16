import json
from pathlib import Path

from openagora_cli.registry.backends.local import LocalBackend
from openagora_cli.registry.registry import DatasetRegistry, default_registry


def test_local_backend(tmp_path: Path):
    data = {
        "datasets": [
            {
                "name": "test",
                "version": "0.1.0",
                "description": "test dataset",
                "task_ids": ["t1"],
                "task_dir": "tasks/t1",
                "tags": ["test"],
            }
        ]
    }
    path = tmp_path / "registry.json"
    path.write_text(json.dumps(data))
    backend = LocalBackend(path)
    specs = backend.list()
    assert len(specs) == 1
    assert specs[0].name == "test"


def test_dataset_registry_deduplicates(tmp_path: Path):
    data = {
        "datasets": [
            {
                "name": "test",
                "version": "0.1.0",
                "description": "test dataset",
                "task_ids": ["t1"],
                "tags": ["test"],
            }
        ]
    }
    path = tmp_path / "registry.json"
    path.write_text(json.dumps(data))
    registry = DatasetRegistry([LocalBackend(path), LocalBackend(path)])
    specs = registry.list()
    assert len(specs) == 1


def test_default_registry_without_env():
    registry = default_registry()
    specs = registry.list()
    assert any(spec.name == "hello-world" for spec in specs)
