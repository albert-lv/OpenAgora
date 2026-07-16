import json

from openagora_cli.trajectory import atif


def test_convert_empty():
    trajectory = atif.convert([], agent_name="test-agent")
    assert trajectory.schema_version == "ATIF-v1.7"
    assert trajectory.agent.name == "test-agent"
    assert trajectory.steps == []


def test_convert_with_messages():
    steps = [
        {
            "step_id": 1,
            "request": {
                "model": "gpt-4",
                "messages_json": json.dumps(
                    [
                        {"role": "system", "content": "You are helpful."},
                        {"role": "user", "content": "Hello"},
                    ]
                ).encode(),
            },
            "response": {
                "choices_json": json.dumps(
                    [{"message": {"role": "assistant", "content": "Hi!"}}]
                ).encode(),
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            },
            "metadata": {},
        }
    ]
    trajectory = atif.convert(steps, agent_name="test-agent", model_name="gpt-4")
    assert len(trajectory.steps) == 3  # system + user + agent
    assert trajectory.steps[0].source == "system"
    assert trajectory.steps[1].source == "user"
    assert trajectory.steps[2].source == "agent"
    assert trajectory.steps[2].message == "Hi!"
    assert trajectory.final_metrics.total_prompt_tokens == 10
    assert trajectory.final_metrics.total_completion_tokens == 5


def test_extract_tool_calls():
    choices = json.dumps(
        [
            {
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "function": {"name": "bash", "arguments": '{"cmd": "ls"}'},
                        }
                    ],
                }
            }
        ]
    ).encode()
    calls = atif._extract_tool_calls(choices)
    assert len(calls) == 1
    assert calls[0].function_name == "bash"
    assert calls[0].arguments == {"cmd": "ls"}


def test_to_json_roundtrip():
    trajectory = atif.convert([], agent_name="x")
    raw = atif.to_json(trajectory)
    data = json.loads(raw)
    assert data["schema_version"] == "ATIF-v1.7"
    assert data["agent"]["name"] == "x"
