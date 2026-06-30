"""Training state aggregation for Code Colosseum."""

import json
import os
from pathlib import Path
from typing import Optional


METRICS_PATH = Path(os.environ.get("TRAINING_METRICS_PATH", "/app/data/metrics.jsonl"))


class TrainingService:
    def __init__(self, metrics_path: Optional[Path] = None):
        self.metrics_path = metrics_path or METRICS_PATH

    def latest_status(self) -> dict:
        """Return the latest training metrics and a synthetic status."""
        status = {
            "running": False,
            "step": 0,
            "avg_reward": 0.0,
            "pass_at_k": 0.0,
            "policy_loss": 0.0,
            "value_loss": 0.0,
            "kl": 0.0,
            "entropy": 0.0,
            "history": [],
        }
        if not self.metrics_path.exists():
            return status

        history = []
        with open(self.metrics_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                history.append(record)

        if not history:
            return status

        latest = history[-1]
        status.update(
            {
                "running": latest.get("running", False),
                "step": latest.get("step", len(history)),
                "avg_reward": latest.get("avg_reward", 0.0),
                "pass_at_k": latest.get("pass_at_k", 0.0),
                "policy_loss": latest.get("policy_loss", 0.0),
                "value_loss": latest.get("value_loss", 0.0),
                "kl": latest.get("kl", 0.0),
                "entropy": latest.get("entropy", 0.0),
                "history": history,
            }
        )
        return status

    def append(self, record: dict):
        self.metrics_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.metrics_path, "a") as f:
            f.write(json.dumps(record) + "\n")
