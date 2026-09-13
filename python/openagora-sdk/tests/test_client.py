import asyncio
import random
import sys
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from openagora.v1 import arena_pb2 as arena_pb
from openagora_sdk.client import ArenaClient, _PollBackoff


def _make_client(**kwargs):
    client = ArenaClient("localhost:9090", **kwargs)
    return client


def _stub_statuses(client, statuses):
    """Replace client.get_rollout with a fake returning the given statuses."""
    calls = []

    def fake_get_rollout(rollout_id):
        calls.append(rollout_id)
        status = statuses[min(len(calls) - 1, len(statuses) - 1)]
        return {
            "rollout_id": rollout_id,
            "task_id": "task",
            "status": status,
            "reward": 1.0,
            "verification_report": None,
        }

    client.get_rollout = fake_get_rollout
    return calls


def test_client_init():
    client = ArenaClient("localhost:9090")
    assert client.endpoint == "localhost:9090"
    client.close()


def test_client_init_poll_defaults():
    client = ArenaClient("localhost:9090")
    assert client.poll_initial_interval == 0.1
    assert client.poll_max_interval == 2.0
    assert client.poll_backoff_multiplier == 2.0
    client.close()


def test_poll_backoff_grows_and_caps(monkeypatch):
    # Force jitter to always pick the upper bound so the schedule is exact.
    monkeypatch.setattr(random, "uniform", lambda lo, hi: hi)
    backoff = _PollBackoff(initial=0.1, maximum=0.5, multiplier=2.0)
    delays = [backoff.next_delay() for _ in range(6)]
    assert delays == [0.1, 0.2, 0.4, 0.5, 0.5, 0.5]


def test_poll_backoff_full_jitter_bounds():
    backoff = _PollBackoff(initial=0.1, maximum=1.0, multiplier=2.0)
    current = 0.1
    for _ in range(10):
        delay = backoff.next_delay()
        assert 0.0 <= delay <= current
        current = min(current * 2.0, 1.0)


def test_poll_backoff_validates_config():
    with pytest.raises(ValueError):
        _PollBackoff(initial=0.0, maximum=1.0, multiplier=2.0)
    with pytest.raises(ValueError):
        _PollBackoff(initial=1.0, maximum=0.5, multiplier=2.0)
    with pytest.raises(ValueError):
        _PollBackoff(initial=0.1, maximum=1.0, multiplier=0.5)


def test_wait_uses_backoff_by_default(monkeypatch):
    client = _make_client()
    monkeypatch.setattr(random, "uniform", lambda lo, hi: hi)
    sleeps = []
    monkeypatch.setattr(time, "sleep", sleeps.append)
    _stub_statuses(client, ["running", "running", "running", "success"])

    info = client.wait("r1")

    assert info["status"] == "success"
    assert sleeps == [0.1, 0.2, 0.4]
    client.close()


def test_wait_fixed_poll_interval_backward_compatible(monkeypatch):
    client = _make_client()
    sleeps = []
    monkeypatch.setattr(time, "sleep", sleeps.append)
    _stub_statuses(client, ["running", "running", "success"])

    info = client.wait("r1", poll_interval=0.5)

    assert info["status"] == "success"
    assert sleeps == [0.5, 0.5]
    client.close()


def test_wait_returns_terminal_statuses(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda _: None)
    for terminal in ("success", "failed", "stopped"):
        client = _make_client()
        _stub_statuses(client, [terminal])
        assert client.wait("r1")["status"] == terminal
        client.close()


def test_wait_timeout(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda _: None)
    client = _make_client()
    _stub_statuses(client, ["running"])

    with pytest.raises(TimeoutError, match="r1 did not complete"):
        client.wait("r1", timeout=-1.0)
    client.close()


def test_wait_async_success(monkeypatch):
    monkeypatch.setattr(random, "uniform", lambda lo, hi: hi)
    sleeps = []
    real_sleep = asyncio.sleep

    async def fake_sleep(delay):
        sleeps.append(delay)
        await real_sleep(0)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    client = _make_client()
    _stub_statuses(client, ["running", "running", "success"])

    info = asyncio.run(client.wait_async("r1"))

    assert info["status"] == "success"
    assert sleeps == [0.1, 0.2]
    client.close()


def test_wait_async_fixed_poll_interval(monkeypatch):
    sleeps = []
    real_sleep = asyncio.sleep

    async def fake_sleep(delay):
        sleeps.append(delay)
        await real_sleep(0)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    client = _make_client()
    _stub_statuses(client, ["running", "success"])

    info = asyncio.run(client.wait_async("r1", poll_interval=0.25))

    assert info["status"] == "success"
    assert sleeps == [0.25]
    client.close()


def test_wait_async_timeout(monkeypatch):
    client = _make_client()
    _stub_statuses(client, ["running"])

    with pytest.raises(TimeoutError, match="r1 did not complete"):
        asyncio.run(client.wait_async("r1", timeout=-1.0))
    client.close()


def test_wait_async_runs_grpc_calls_off_event_loop():
    client = _make_client()
    threads = []

    def fake_get_rollout(rollout_id):
        threads.append(threading.get_ident())
        return {
            "rollout_id": rollout_id,
            "task_id": "task",
            "status": "success",
            "reward": 1.0,
            "verification_report": None,
        }

    client.get_rollout = fake_get_rollout

    info = asyncio.run(client.wait_async("r1"))

    assert info["status"] == "success"
    assert threads and threads[0] != threading.get_ident()
    client.close()


def test_pause_rollout():
    client = _make_client()
    client.stub = MagicMock()
    client.stub.PauseRollout.return_value = arena_pb.PauseRolloutResponse()

    client.pause_rollout("r1")

    req = client.stub.PauseRollout.call_args.args[0]
    assert req.rollout_id == "r1"
    assert req.mode == "freeze"
    client.close()


def test_pause_rollout_custom_mode():
    client = _make_client()
    client.stub = MagicMock()
    client.stub.PauseRollout.return_value = arena_pb.PauseRolloutResponse()

    client.pause_rollout("r1", mode="snapshot")

    req = client.stub.PauseRollout.call_args.args[0]
    assert req.mode == "snapshot"
    client.close()


def test_resume_rollout():
    client = _make_client()
    client.stub = MagicMock()
    client.stub.ResumeRollout.return_value = arena_pb.ResumeRolloutResponse(
        proxy_url="http://localhost:8080", token="tok-123"
    )

    out = client.resume_rollout("r1")

    req = client.stub.ResumeRollout.call_args.args[0]
    assert req.rollout_id == "r1"
    assert out == {"proxy_url": "http://localhost:8080", "token": "tok-123"}
    client.close()


def test_update_weights():
    client = _make_client()
    client.stub = MagicMock()
    client.stub.UpdateWeights.return_value = arena_pb.UpdateWeightsResponse(
        success=True, message="ok", weight_version="v7"
    )

    out = client.update_weights("/ckpt/step-7", "v7", abort_in_flight=True)

    req = client.stub.UpdateWeights.call_args.args[0]
    assert req.model_path == "/ckpt/step-7"
    assert req.weight_version == "v7"
    assert req.abort_in_flight is True
    assert out == {"success": True, "message": "ok", "weight_version": "v7"}
    client.close()


def test_update_weights_defaults_no_abort():
    client = _make_client()
    client.stub = MagicMock()
    client.stub.UpdateWeights.return_value = arena_pb.UpdateWeightsResponse(
        success=False, message="vllm disk reload unsupported", weight_version="v1"
    )

    out = client.update_weights("/ckpt/step-1", "v1")

    req = client.stub.UpdateWeights.call_args.args[0]
    assert req.abort_in_flight is False
    assert out["success"] is False
    client.close()


def test_update_weights_async():
    client = _make_client()
    client.stub = MagicMock()
    client.stub.UpdateWeights.return_value = arena_pb.UpdateWeightsResponse(
        success=True, message="ok", weight_version="v2"
    )

    out = asyncio.run(client.update_weights_async("/ckpt/step-2", "v2"))

    req = client.stub.UpdateWeights.call_args.args[0]
    assert req.model_path == "/ckpt/step-2"
    assert out["weight_version"] == "v2"
    client.close()


def test_wait_return_on_pause_returns_paused(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda _: None)
    client = _make_client()
    _stub_statuses(client, ["running", "paused"])

    info = client.wait("r1", return_on_pause=True)

    assert info["status"] == "paused"
    client.close()


def test_wait_paused_is_not_terminal_by_default(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda _: None)
    client = _make_client()
    _stub_statuses(client, ["paused", "paused", "success"])

    info = client.wait("r1")

    assert info["status"] == "success"
    client.close()


def test_wait_async_return_on_pause(monkeypatch):
    real_sleep = asyncio.sleep

    async def fake_sleep(delay):
        await real_sleep(0)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    client = _make_client()
    _stub_statuses(client, ["running", "paused"])

    info = asyncio.run(client.wait_async("r1", return_on_pause=True))

    assert info["status"] == "paused"
    client.close()


def test_wait_async_paused_is_not_terminal_by_default(monkeypatch):
    real_sleep = asyncio.sleep

    async def fake_sleep(delay):
        await real_sleep(0)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    client = _make_client()
    _stub_statuses(client, ["paused", "success"])

    info = asyncio.run(client.wait_async("r1"))

    assert info["status"] == "success"
    client.close()
