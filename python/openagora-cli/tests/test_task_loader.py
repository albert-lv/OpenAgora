import json
from pathlib import Path

from openagora_cli.task.loader import load_task


FIXTURES = Path(__file__).parent / "fixtures"


def test_load_task_dir():
    bundle = load_task(FIXTURES / "hello-world")
    assert bundle.task_id == "hello-world"
    assert "hello, world" in bundle.instruction
    assert bundle.config.environment.image == "openagora-agent-minimal:latest"


def test_to_task_json():
    bundle = load_task(FIXTURES / "hello-world")
    data = bundle.to_task_json()
    assert data["task_id"] == "hello-world"
    assert "solution.hello" in bundle.config.to_verify_dict()["command"]


def test_to_task_file_bytes():
    bundle = load_task(FIXTURES / "hello-world")
    raw = bundle.to_task_file_bytes()
    data = json.loads(raw)
    assert data["task_id"] == "hello-world"
