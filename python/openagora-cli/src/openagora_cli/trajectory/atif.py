"""ATIF (Agent Trajectory Interchange Format) v1.7 export support.

Converts OpenAgora internal trajectories to the Harbor ATIF JSON schema.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel, Field


class AgentSchema(BaseModel):
    name: str
    version: str = "0.1.0"
    model_name: Optional[str] = None
    extra: dict[str, Any] = Field(default_factory=dict)


class FinalMetricsSchema(BaseModel):
    total_prompt_tokens: Optional[int] = None
    total_completion_tokens: Optional[int] = None
    total_steps: Optional[int] = None
    extra: dict[str, Any] = Field(default_factory=dict)


class MetricsSchema(BaseModel):
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    cost_usd: Optional[float] = None
    extra: dict[str, Any] = Field(default_factory=dict)


class ToolCallSchema(BaseModel):
    tool_call_id: str
    function_name: str
    arguments: dict[str, Any]
    extra: dict[str, Any] = Field(default_factory=dict)


class ObservationResultSchema(BaseModel):
    source_call_id: Optional[str] = None
    content: Optional[str] = None
    extra: dict[str, Any] = Field(default_factory=dict)


class ObservationSchema(BaseModel):
    results: list[ObservationResultSchema]


class StepObject(BaseModel):
    step_id: int
    timestamp: Optional[str] = None
    source: str  # system | user | agent
    model_name: Optional[str] = None
    message: Any = ""
    reasoning_content: Optional[str] = None
    tool_calls: list[ToolCallSchema] = Field(default_factory=list)
    observation: Optional[ObservationSchema] = None
    metrics: Optional[MetricsSchema] = None
    extra: dict[str, Any] = Field(default_factory=dict)


class Trajectory(BaseModel):
    schema_version: str = "ATIF-v1.7"
    trajectory_id: str
    session_id: Optional[str] = None
    agent: AgentSchema
    steps: list[StepObject]
    notes: Optional[str] = None
    final_metrics: Optional[FinalMetricsSchema] = None
    extra: dict[str, Any] = Field(default_factory=dict)


def _iso(ts: Optional[datetime]) -> Optional[str]:
    if ts is None:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.isoformat().replace("+00:00", "Z")


def _extract_messages(messages_json: bytes | None) -> list[dict[str, Any]]:
    if not messages_json:
        return []
    try:
        data = json.loads(messages_json)
        if isinstance(data, list):
            return data
        return [data]
    except (json.JSONDecodeError, TypeError):
        return []


def _message_to_string(message: dict[str, Any]) -> str:
    if isinstance(message.get("content"), str):
        return message["content"]
    if isinstance(message.get("content"), list):
        parts = []
        for part in message["content"]:
            if isinstance(part, dict) and part.get("type") == "text":
                parts.append(part.get("text", ""))
        return "\n".join(parts)
    return json.dumps(message, ensure_ascii=False)


def _extract_tool_calls(choices_json: bytes | None) -> list[ToolCallSchema]:
    if not choices_json:
        return []
    try:
        choices = json.loads(choices_json)
        if not isinstance(choices, list):
            choices = [choices]
        calls: list[ToolCallSchema] = []
        for choice in choices:
            message = choice.get("message", {}) if isinstance(choice, dict) else {}
            for tc in message.get("tool_calls", []):
                if not isinstance(tc, dict):
                    continue
                function = tc.get("function", {})
                args: dict[str, Any] = {}
                try:
                    args = json.loads(function.get("arguments", "{}"))
                except (json.JSONDecodeError, TypeError):
                    pass
                calls.append(
                    ToolCallSchema(
                        tool_call_id=tc.get("id", ""),
                        function_name=function.get("name", "unknown"),
                        arguments=args,
                    )
                )
        return calls
    except (json.JSONDecodeError, TypeError):
        return []


def _extract_response_text(choices_json: bytes | None) -> str:
    if not choices_json:
        return ""
    try:
        choices = json.loads(choices_json)
        if not isinstance(choices, list):
            choices = [choices]
        parts = []
        for choice in choices:
            message = choice.get("message", {}) if isinstance(choice, dict) else {}
            content = message.get("content")
            if isinstance(content, str):
                parts.append(content)
            elif isinstance(content, list):
                for part in content:
                    if isinstance(part, dict) and part.get("type") == "text":
                        parts.append(part.get("text", ""))
        return "\n".join(parts)
    except (json.JSONDecodeError, TypeError):
        return ""


def convert(
    steps: list[dict[str, Any]],
    agent_name: str = "arena-minimal",
    model_name: Optional[str] = None,
) -> Trajectory:
    """Convert OpenAgora SDK trajectory steps to ATIF v1.7."""
    atif_steps: list[StepObject] = []
    total_prompt = 0
    total_completion = 0

    for step in steps:
        _ = step.get("step_id", len(atif_steps) + 1)
        ts = step.get("timestamp")
        if isinstance(ts, datetime):
            ts = _iso(ts)
        elif isinstance(ts, (int, float)):
            ts = (
                datetime.fromtimestamp(ts, tz=timezone.utc)
                .isoformat()
                .replace("+00:00", "Z")
            )

        request = step.get("request") or {}
        response = step.get("response") or {}
        usage = response.get("usage") or {}

        messages = _extract_messages(request.get("messages_json"))
        # Add user/system messages as separate steps before the agent step.
        for msg in messages:
            role = msg.get("role", "user")
            if role in ("system", "user"):
                atif_steps.append(
                    StepObject(
                        step_id=len(atif_steps) + 1,
                        timestamp=ts,
                        source=role,
                        message=_message_to_string(msg),
                    )
                )

        tool_calls = _extract_tool_calls(response.get("choices_json"))
        agent_message = _extract_response_text(response.get("choices_json"))
        observation = None
        if tool_calls:
            observation = ObservationSchema(
                results=[
                    ObservationResultSchema(
                        source_call_id=tc.tool_call_id,
                        content="",
                    )
                    for tc in tool_calls
                ]
            )

        metrics = None
        prompt_tokens = usage.get("prompt_tokens") or 0
        completion_tokens = usage.get("completion_tokens") or 0
        if prompt_tokens or completion_tokens:
            metrics = MetricsSchema(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
            )
            total_prompt += prompt_tokens
            total_completion += completion_tokens

        atif_steps.append(
            StepObject(
                step_id=len(atif_steps) + 1,
                timestamp=ts,
                source="agent",
                model_name=request.get("model") or model_name,
                message=agent_message,
                tool_calls=tool_calls,
                observation=observation,
                metrics=metrics,
                extra={"metadata": step.get("metadata", {})},
            )
        )

    final_metrics = None
    if total_prompt or total_completion:
        final_metrics = FinalMetricsSchema(
            total_prompt_tokens=total_prompt,
            total_completion_tokens=total_completion,
            total_steps=len(atif_steps),
        )

    return Trajectory(
        trajectory_id=str(uuid.uuid4()),
        agent=AgentSchema(name=agent_name, model_name=model_name),
        steps=atif_steps,
        final_metrics=final_metrics,
    )


def to_json(trajectory: Trajectory, indent: int = 2) -> str:
    return trajectory.model_dump_json(indent=indent, exclude_none=True)
