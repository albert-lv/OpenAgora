"""Thin wrapper around openagora_sdk.ArenaClient for the orchestrator."""

import json
import os
from typing import Optional

from openagora_sdk.client import ArenaClient


ARENA_ENDPOINT = os.environ.get("ARENA_ENDPOINT", "localhost:9090")
ARENA_AGENT_IMAGE = os.environ.get(
    "ARENA_AGENT_IMAGE", "openagora-code-colosseum-agent:latest"
)
ARENA_LLM_BACKEND = os.environ.get("ARENA_LLM_BACKEND", "http://localhost:8000/v1")

LLM_BACKENDS = {
    "mock": os.environ.get("ARENA_MOCK_LLM_BACKEND", "http://mock-llm:8000/v1"),
    "claude": os.environ.get("ARENA_CLAUDE_LLM_BACKEND", "http://claude-llm:8000/v1"),
    "codex": os.environ.get("ARENA_CODEX_LLM_BACKEND", "http://codex-llm:8000/v1"),
    "opencode": os.environ.get(
        "ARENA_OPENCODE_LLM_BACKEND", "http://opencode-llm:8000/v1"
    ),
    "kimi": os.environ.get("ARENA_KIMI_LLM_BACKEND", "http://kimi-llm:8000/v1"),
}


class ArenaWrapper:
    def __init__(
        self,
        endpoint: Optional[str] = None,
        agent_image: Optional[str] = None,
        llm_backend: Optional[str] = None,
    ):
        self.endpoint = endpoint or ARENA_ENDPOINT
        self.agent_image = agent_image or ARENA_AGENT_IMAGE
        self.llm_backend = llm_backend or ARENA_LLM_BACKEND
        self._client = ArenaClient(self.endpoint)

    def create_rollout(
        self,
        task_id: str,
        task_file: bytes,
        verify_command: str,
        sampling: Optional[dict] = None,
        agent_type: str = "mock",
    ) -> dict:
        """Create a new Arena rollout."""
        llm_backend = LLM_BACKENDS.get(agent_type, self.llm_backend)

        return self._client.create_rollout(
            task_id=task_id,
            image=self.agent_image,
            llm_backend=llm_backend,
            sampling=sampling
            or {"temperature": 0.3, "top_p": 0.9, "max_tokens_budget": 2048},
            verify={"command": verify_command, "timeout_seconds": 300},
            task_file=task_file,
            memory="4g",
            cpus=1.0,
            timeout_seconds=600,
        )

    def get_rollout(self, rollout_id: str) -> dict:
        return self._client.get_rollout(rollout_id)

    def get_trajectory(self, rollout_id: str) -> list[dict]:
        return self._client.get_trajectory(rollout_id)

    def list_rollouts(self) -> list[dict]:
        return self._client.list_rollouts()

    def close(self):
        self._client.close()


def extract_code_from_trajectory(trajectory: list[dict]) -> str:
    """Extract the latest assistant code block from a trajectory.

    Note: the Arena proxy currently stores the full response body in
    choices_json, not just the choices array. We handle both shapes.
    """
    for step in reversed(trajectory):
        response = step.get("response") or {}
        choices_json = response.get("choices_json")
        if not choices_json:
            continue
        if isinstance(choices_json, bytes):
            choices_json = choices_json.decode("utf-8")
        try:
            payload = json.loads(choices_json)
        except json.JSONDecodeError:
            continue
        if not payload:
            continue

        # If choices_json is the full response body, unwrap "choices".
        choices = payload.get("choices") if isinstance(payload, dict) else payload
        if not choices or not isinstance(choices, list):
            continue

        first_choice = choices[0]
        if not isinstance(first_choice, dict):
            continue

        message = first_choice.get("message", {})
        if not isinstance(message, dict):
            continue

        content = message.get("content", "")
        code = _extract_code_block(content)
        if code:
            return code
    return ""


def extract_usage_from_trajectory(trajectory: list[dict]) -> dict:
    """Sum prompt/completion tokens across all trajectory steps.

    Returns a dict with prompt_tokens, completion_tokens, total_tokens, and
    steps (number of LLM calls).  The proxy records usage per response.
    """
    prompt = 0
    completion = 0
    steps = 0
    for step in trajectory:
        response = step.get("response") or {}
        usage = response.get("usage") or {}
        if usage:
            prompt += int(usage.get("prompt_tokens", 0))
            completion += int(usage.get("completion_tokens", 0))
            steps += 1
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": prompt + completion,
        "steps": steps,
    }


def _extract_code_block(content: str) -> str:
    if "```python" in content:
        return content.split("```python")[1].split("```")[0].strip()
    if "```" in content:
        return content.split("```")[1].split("```")[0].strip()
    return content.strip()
