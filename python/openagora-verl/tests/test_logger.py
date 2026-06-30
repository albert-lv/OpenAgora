"""Unit tests for openagora_verl loggers."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


from openagora_verl.logger import (
    CompositeLogger,
    ConsoleLogger,
    NoOpLogger,
    TensorBoardLogger,
)


def test_noop_logger_does_not_raise():
    logger = NoOpLogger()
    logger.log_rollout(
        global_step=1,
        rollout_id="r1",
        reward=1.0,
        num_turns=2,
        response_length=10,
        prompt_length=5,
        latency_seconds=1.0,
        status="success",
    )


def test_console_logger_does_not_raise(caplog):
    logger = ConsoleLogger()
    with caplog.at_level("INFO"):
        logger.log_rollout(
            global_step=1,
            rollout_id="r1",
            reward=1.0,
            num_turns=2,
            response_length=10,
            prompt_length=5,
            latency_seconds=1.0,
            status="success",
        )
    assert "r1" in caplog.text


def test_tensorboard_logger_requires_optional_dependency(tmp_path):
    logger = TensorBoardLogger(log_dir=str(tmp_path))
    # Writing should work if tensorboard/torch is installed.
    logger.log_rollout(
        global_step=1,
        rollout_id="r1",
        reward=1.0,
        num_turns=2,
        response_length=10,
        prompt_length=5,
        latency_seconds=1.0,
        status="success",
    )
    logger.close()


def test_composite_logger_forwards_to_children():
    class DummyLogger(NoOpLogger):
        def __init__(self):
            self.calls = 0

        def log_rollout(self, **kwargs):
            self.calls += 1

    a = DummyLogger()
    b = DummyLogger()
    logger = CompositeLogger([a, b])
    logger.log_rollout(
        global_step=1,
        rollout_id="r1",
        reward=1.0,
        num_turns=2,
        response_length=10,
        prompt_length=5,
        latency_seconds=1.0,
        status="success",
    )
    assert a.calls == 1
    assert b.calls == 1


def test_composite_logger_is_fault_tolerant():
    class FailingLogger(NoOpLogger):
        def log_rollout(self, **kwargs):
            raise RuntimeError("boom")

    logger = CompositeLogger([FailingLogger(), NoOpLogger()])
    logger.log_rollout(
        global_step=1,
        rollout_id="r1",
        reward=1.0,
        num_turns=2,
        response_length=10,
        prompt_length=5,
        latency_seconds=1.0,
        status="success",
    )
