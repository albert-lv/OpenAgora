"""GitHub-backed registry backend using sparse checkout.

This is a Harbor-style backend: the registry JSON lives in a GitHub repo and
we sparse-checkout only the dataset/task directories we need.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Optional

from openagora_cli.registry.backends.base import RegistryBackend
from openagora_cli.registry.models import DatasetSpec


class GitHubBackend(RegistryBackend):
    """Reads datasets from a GitHub repository via sparse checkout."""

    name = "github"

    def __init__(
        self, repo: str, ref: str = "main", registry_path: str = "registry.json"
    ):
        # repo may be "owner/name" or a full URL.
        self._repo = repo
        self._ref = ref
        self._registry_path = registry_path
        self._cache_dir = (
            Path.home()
            / ".cache"
            / "arena"
            / "github-registries"
            / repo.replace("/", "--")
        )

    def _ensure_cloned(self) -> None:
        if (self._cache_dir / ".git").exists():
            # Pull latest.
            subprocess.run(
                ["git", "fetch", "origin", self._ref],
                cwd=self._cache_dir,
                check=True,
                capture_output=True,
            )
            subprocess.run(
                ["git", "checkout", "origin/" + self._ref],
                cwd=self._cache_dir,
                check=True,
                capture_output=True,
            )
            return

        self._cache_dir.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [
                "git",
                "clone",
                "--depth",
                "1",
                "--branch",
                self._ref,
                "--filter=blob:none",
                "--sparse",
                f"https://github.com/{self._repo}.git",
                str(self._cache_dir),
            ],
            check=True,
            capture_output=True,
        )

    def _read_registry(self) -> dict:
        self._ensure_cloned()
        registry_file = self._cache_dir / self._registry_path
        if not registry_file.exists():
            raise RuntimeError(f"registry file not found: {registry_file}")
        return json.loads(registry_file.read_text(encoding="utf-8"))

    def list(self) -> list[DatasetSpec]:
        data = self._read_registry()
        return [DatasetSpec.model_validate(d) for d in data.get("datasets", [])]

    def load(self, name: str, version: Optional[str] = None) -> Optional[DatasetSpec]:
        for spec in self.list():
            if spec.name == name and (version is None or spec.version == version):
                # Sparse-checkout the task dir so it is usable.
                if spec.task_dir:
                    subprocess.run(
                        [
                            "git",
                            "sparse-checkout",
                            "set",
                            spec.task_dir,
                            self._registry_path,
                        ],
                        cwd=self._cache_dir,
                        check=True,
                        capture_output=True,
                    )
                    subprocess.run(
                        ["git", "checkout"],
                        cwd=self._cache_dir,
                        check=True,
                        capture_output=True,
                    )
                    return spec.model_copy(
                        update={"task_dir": str(self._cache_dir / spec.task_dir)}
                    )
                return spec
        return None
