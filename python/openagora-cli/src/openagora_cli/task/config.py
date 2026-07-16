"""Task manifest models for Arena task.toml files."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field, model_validator


class PackageInfo(BaseModel):
    name: Optional[str] = None
    version: Optional[str] = None
    description: Optional[str] = None
    author: Optional[str] = None


class EnvironmentConfig(BaseModel):
    image: Optional[str] = None
    dockerfile: Optional[str] = None
    compose: Optional[str] = None
    memory: Optional[str] = "8g"
    cpus: float = 2.0
    timeout_seconds: int = 3600
    env_vars: dict[str, str] = Field(default_factory=dict)
    workdir: Optional[str] = None

    @model_validator(mode="after")
    def check_image_or_dockerfile(self):
        if self.image is None and self.dockerfile is None and self.compose is None:
            # Allow empty for local provider where image is the command.
            pass
        return self


class AgentConfig(BaseModel):
    name: Optional[str] = None
    model: Optional[str] = None
    max_turns: Optional[int] = None
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    skills: list[str] = Field(default_factory=list)
    env_vars: dict[str, str] = Field(default_factory=dict)


class VerifierConfig(BaseModel):
    command: Optional[str] = None
    framework: Optional[str] = None
    language: Optional[str] = None
    timeout_seconds: int = 300
    working_directory: Optional[str] = None
    install_command: Optional[str] = None
    baseline_command: Optional[str] = None
    patch_command: Optional[str] = None
    pass_to_pass: list[str] = Field(default_factory=list)
    fail_to_pass: list[str] = Field(default_factory=list)


class RewardConfig(BaseModel):
    name: str
    weight: float = 1.0
    verifier_dir: Optional[str] = None
    command: Optional[str] = None
    aggregation: str = "mean"  # mean, all_pass, max


class ArtifactConfig(BaseModel):
    path: str
    name: Optional[str] = None


class TaskConfig(BaseModel):
    schema_version: str = "1.0"
    task: Optional[PackageInfo] = None
    environment: EnvironmentConfig = Field(default_factory=EnvironmentConfig)
    agent: AgentConfig = Field(default_factory=AgentConfig)
    verifier: VerifierConfig = Field(default_factory=VerifierConfig)
    rewards: list[RewardConfig] = Field(default_factory=list)
    artifacts: list[str | ArtifactConfig] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def has_multi_reward(self) -> bool:
        return len(self.rewards) > 1

    @property
    def task_id(self) -> str:
        if self.task and self.task.name:
            return self.task.name
        return "unknown-task"

    @property
    def description(self) -> str:
        if self.task and self.task.description:
            return self.task.description
        return ""

    def to_task_json(self, instruction: str) -> dict[str, Any]:
        """Convert to the legacy task.json format consumed by the Arena server."""
        return {
            "task_id": self.task_id,
            "description": instruction or self.description,
            "sandbox_image": self.environment.image,
            "environment": {
                "memory": self.environment.memory,
                "cpus": self.environment.cpus,
                "timeout_seconds": self.environment.timeout_seconds,
                "env_vars": self.environment.env_vars,
                "workdir": self.environment.workdir,
            },
            "agent": {
                "name": self.agent.name,
                "model": self.agent.model,
                "max_turns": self.agent.max_turns,
                "temperature": self.agent.temperature,
                "top_p": self.agent.top_p,
                "skills": self.agent.skills,
            },
            "metadata": self.metadata,
        }

    def to_verify_dict(self) -> dict[str, Any]:
        """Convert verifier config to the SDK verify dict."""
        return {
            "command": self.verifier.command or "true",
            "framework": self.verifier.framework or "",
            "language": self.verifier.language or "",
            "timeout_seconds": self.verifier.timeout_seconds,
            "working_directory": self.verifier.working_directory or "",
            "install_command": self.verifier.install_command or "",
            "baseline_command": self.verifier.baseline_command or "",
            "patch_command": self.verifier.patch_command or "",
            "pass_to_pass": self.verifier.pass_to_pass,
            "fail_to_pass": self.verifier.fail_to_pass,
            "rewards": [
                {
                    "name": r.name,
                    "weight": r.weight,
                    "verifier_dir": r.verifier_dir or "",
                    "command": r.command or "",
                    "aggregation": r.aggregation,
                }
                for r in self.rewards
            ],
        }
