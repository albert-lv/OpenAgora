"""Plugin manager: discovers and dispatches to enabled plugins."""

from __future__ import annotations

from typing import Any

from openagora_cli.plugins.base import Plugin
from openagora_cli.plugins.langsmith import LangSmithPlugin
from openagora_cli.plugins.wandb import WandbPlugin


class PluginManager:
    """Discovers and invokes plugins for the Arena CLI."""

    def __init__(self):
        self._plugins: list[Plugin] = []
        for cls in (LangSmithPlugin, WandbPlugin):
            inst = cls()
            if inst.is_enabled():
                self._plugins.append(inst)

    def on_job_start(self, job_context: dict[str, Any]) -> None:
        for p in self._plugins:
            try:
                p.on_job_start(job_context)
            except Exception as exc:
                print(f"[{p.name}] plugin error in on_job_start: {exc}")

    def on_rollout_start(self, rollout_id: str, context: dict[str, Any]) -> None:
        for p in self._plugins:
            try:
                p.on_rollout_start(rollout_id, context)
            except Exception as exc:
                print(f"[{p.name}] plugin error in on_rollout_start: {exc}")

    def on_rollout_end(self, rollout_id: str, result: dict[str, Any]) -> None:
        for p in self._plugins:
            try:
                p.on_rollout_end(rollout_id, result)
            except Exception as exc:
                print(f"[{p.name}] plugin error in on_rollout_end: {exc}")

    def on_job_end(self, job_context: dict[str, Any]) -> None:
        for p in self._plugins:
            try:
                p.on_job_end(job_context)
            except Exception as exc:
                print(f"[{p.name}] plugin error in on_job_end: {exc}")

    @property
    def enabled_plugins(self) -> list[str]:
        return [p.name for p in self._plugins]
