"""LangSmith observability plugin for Arena CLI."""

from __future__ import annotations

import os
from typing import Any

from openagora_cli.plugins.base import Plugin


class LangSmithPlugin(Plugin):
    """Uploads Arena rollouts to LangSmith as runs inside a project.

    Enable by setting ``LANGSMITH_API_KEY`` in the environment. Optionally set
    ``LANGSMITH_PROJECT`` (default: "openagora") and ``LANGSMITH_ENDPOINT``.
    """

    name = "langsmith"

    def __init__(self):
        self._project = os.environ.get("LANGSMITH_PROJECT", "openagora")

    def _get_client(self):
        # Lazy import so LangSmith is only required when the plugin is enabled.
        try:
            from langsmith import Client
        except ImportError as e:
            raise RuntimeError(
                "LangSmith plugin requires 'langsmith'. Install with: "
                "pip install 'openagora-cli[langsmith]'"
            ) from e
        endpoint = os.environ.get("LANGSMITH_ENDPOINT")
        return Client(api_key=os.environ.get("LANGSMITH_API_KEY"), api_url=endpoint)

    def is_enabled(self) -> bool:
        return bool(os.environ.get("LANGSMITH_API_KEY"))

    def on_job_start(self, job_context: dict[str, Any]) -> None:
        # Ensure the project exists. create_project is idempotent in recent
        # LangSmith versions; we ignore conflicts.
        client = self._get_client()
        try:
            client.create_project(self._project)
        except Exception:
            pass

    def on_rollout_start(self, rollout_id: str, context: dict[str, Any]) -> None:
        # Runs are created lazily on rollout end so we have inputs+outputs.
        pass

    def on_rollout_end(self, rollout_id: str, result: dict[str, Any]) -> None:
        client = self._get_client()
        inputs = {
            "task_id": result.get("task_id"),
            "instruction": result.get("instruction", ""),
            "agent": result.get("agent"),
            "provider": result.get("provider"),
            "model": result.get("model"),
        }
        outputs = {
            "status": result.get("status"),
            "reward": result.get("reward"),
            "verification_report": result.get("verification_report"),
        }
        try:
            client.create_run(
                name=f"arena-{rollout_id[:8]}",
                run_type="chain",
                project_name=self._project,
                inputs=inputs,
                outputs=outputs,
                error=result.get("error"),
                extra={
                    "rollout_id": rollout_id,
                    "trajectory_path": result.get("trajectory_path"),
                },
            )
        except Exception as exc:
            # Observability plugins must not fail the main job.
            print(f"[langsmith] warning: failed to log run: {exc}")

    def on_job_end(self, job_context: dict[str, Any]) -> None:
        pass
