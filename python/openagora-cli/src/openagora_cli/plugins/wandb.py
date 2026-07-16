"""Weights & Biases observability plugin for Arena CLI."""

from __future__ import annotations

import os
from typing import Any

from openagora_cli.plugins.base import Plugin


class WandbPlugin(Plugin):
    """Logs Arena rollouts to Weights & Biases.

    Enable by setting ``WANDB_API_KEY`` in the environment. Optionally set
    ``WANDB_PROJECT`` (default: "openagora") and ``WANDB_ENTITY``.
    """

    name = "wandb"

    def __init__(self):
        self._project = os.environ.get("WANDB_PROJECT", "openagora")
        self._entity = os.environ.get("WANDB_ENTITY")
        self._run = None

    def _init_wandb(self):
        try:
            import wandb
        except ImportError as e:
            raise RuntimeError(
                "W&B plugin requires 'wandb'. Install with: "
                "pip install 'openagora-cli[wandb]'"
            ) from e
        return wandb

    def is_enabled(self) -> bool:
        return bool(os.environ.get("WANDB_API_KEY"))

    def on_job_start(self, job_context: dict[str, Any]) -> None:
        wandb = self._init_wandb()
        self._run = wandb.init(
            project=self._project,
            entity=self._entity,
            job_type="arena-run",
            config=job_context,
        )

    def on_rollout_start(self, rollout_id: str, context: dict[str, Any]) -> None:
        pass

    def on_rollout_end(self, rollout_id: str, result: dict[str, Any]) -> None:
        if self._run is None:
            return
        metrics = {"reward": result.get("reward", 0.0)}
        report = result.get("verification_report") or {}
        for rw in report.get("rewards", []):
            metrics[f"reward/{rw.get('name', 'unknown')}"] = rw.get("value", 0.0)

        try:
            self._run.log({f"rollout/{rollout_id[:8]}": metrics})

            trajectory_path = result.get("trajectory_path")
            if trajectory_path:
                artifact = self._init_wandb().Artifact(
                    name=f"trajectory-{rollout_id[:8]}",
                    type="atif-trajectory",
                )
                artifact.add_file(trajectory_path)
                self._run.log_artifact(artifact)
        except Exception as exc:
            print(f"[wandb] warning: failed to log rollout: {exc}")

    def on_job_end(self, job_context: dict[str, Any]) -> None:
        if self._run is not None:
            self._run.finish()
            self._run = None
