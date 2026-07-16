"""Load Arena task.toml + instruction.md + tests/ directories."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import toml

from .config import TaskConfig


class TaskBundle:
    """A loaded task with its config, instruction, and test directory."""

    def __init__(
        self,
        config: TaskConfig,
        instruction: str,
        tests_dir: Path | None = None,
        task_dir: Path | None = None,
    ):
        self.config = config
        self.instruction = instruction
        self.tests_dir = tests_dir
        self.task_dir = task_dir

    @property
    def task_id(self) -> str:
        return self.config.task_id

    def to_task_json(self) -> dict[str, Any]:
        return self.config.to_task_json(self.instruction)

    def to_task_file_bytes(self) -> bytes:
        return json.dumps(self.to_task_json(), ensure_ascii=False, indent=2).encode(
            "utf-8"
        )


def load_task(path: str | Path) -> TaskBundle:
    """Load a task from a directory or a legacy task.json file."""
    p = Path(path)
    if p.is_file():
        return _load_task_json(p)
    return _load_task_dir(p)


def _load_task_dir(task_dir: Path) -> TaskBundle:
    if not task_dir.is_dir():
        raise FileNotFoundError(f"task directory not found: {task_dir}")

    config_path = task_dir / "task.toml"
    instruction_path = task_dir / "instruction.md"
    tests_dir = task_dir / "tests"

    if not config_path.exists():
        raise FileNotFoundError(f"task.toml not found in {task_dir}")

    raw = toml.load(config_path)

    # Load optional tests/reward.toml and merge into config.rewards.
    reward_toml_path = tests_dir / "reward.toml"
    if reward_toml_path.exists():
        reward_raw = toml.load(reward_toml_path)
        rewards = reward_raw.get("reward", [])
        if rewards and "rewards" not in raw:
            raw["rewards"] = rewards

    config = TaskConfig.model_validate(raw)

    instruction = ""
    if instruction_path.exists():
        instruction = instruction_path.read_text(encoding="utf-8")

    return TaskBundle(
        config=config,
        instruction=instruction,
        tests_dir=tests_dir if tests_dir.exists() else None,
        task_dir=task_dir,
    )


def _load_task_json(task_file: Path) -> TaskBundle:
    data = json.loads(task_file.read_text(encoding="utf-8"))
    config = _task_json_to_config(data)
    return TaskBundle(
        config=config,
        instruction=data.get("description", ""),
        task_dir=task_file.parent,
    )


def _task_json_to_config(data: dict[str, Any]) -> TaskConfig:
    """Best-effort conversion from legacy task.json to TaskConfig."""
    env = data.get("environment", {})
    agent = data.get("agent", {})
    verify = data.get("verify", {})
    return TaskConfig(
        task=PackageInfo(  # type: ignore[arg-type]
            name=data.get("task_id", "unknown"),
            description=data.get("description", ""),
        ),
        environment=EnvironmentConfig(  # type: ignore[arg-type]
            image=data.get("sandbox_image"),
            memory=env.get("memory", "8g"),
            cpus=env.get("cpus", 2.0),
            timeout_seconds=env.get("timeout_seconds", 3600),
            env_vars=env.get("env_vars", {}),
            workdir=env.get("workdir"),
        ),
        agent=AgentConfig(  # type: ignore[arg-type]
            name=agent.get("name"),
            model=agent.get("model"),
            max_turns=agent.get("max_turns"),
            temperature=agent.get("temperature"),
            top_p=agent.get("top_p"),
            skills=agent.get("skills", []),
        ),
        verifier=VerifierConfig(  # type: ignore[arg-type]
            command=verify.get("command") if isinstance(verify, dict) else verify,
            framework=verify.get("framework", "") if isinstance(verify, dict) else "",
            timeout_seconds=verify.get("timeout_seconds", 300)
            if isinstance(verify, dict)
            else 300,
            working_directory=verify.get("working_directory", "")
            if isinstance(verify, dict)
            else "",
        ),
    )


# Import here to avoid circular import with config.py
from .config import AgentConfig, EnvironmentConfig, PackageInfo, VerifierConfig  # noqa: E402
