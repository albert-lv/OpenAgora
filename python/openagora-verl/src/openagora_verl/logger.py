"""Experiment tracking loggers for the Arena veRL integration.

This module provides thin adapters for common experiment tracking tools so that
users can log per-rollout metrics without coupling ``ArenaAgentLoop`` to any
specific vendor. All loggers share the same ``TrainingLogger`` interface and can
be combined via ``CompositeLogger``.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any, Optional

logger = logging.getLogger(__name__)


class TrainingLogger(ABC):
    """Abstract interface for logging training-time metrics."""

    @abstractmethod
    def log_rollout(
        self,
        *,
        global_step: int,
        rollout_id: str,
        reward: float,
        num_turns: int,
        response_length: int,
        prompt_length: int,
        latency_seconds: float,
        status: str,
        extra: Optional[dict[str, Any]] = None,
    ) -> None:
        """Log metrics for a single rollout.

        Args:
            global_step: Current training global step.
            rollout_id: Arena rollout identifier.
            reward: Reward returned by the verification plane.
            num_turns: Number of agent turns in the rollout.
            response_length: Number of response tokens.
            prompt_length: Number of prompt tokens.
            latency_seconds: End-to-end rollout latency.
            status: Arena rollout status (e.g. ``success`` or ``failed``).
            extra: Optional additional key-value metrics.
        """

    def log_scalar(self, key: str, value: float, step: int) -> None:
        """Log an arbitrary scalar metric."""

    def close(self) -> None:
        """Flush and release resources."""


class NoOpLogger(TrainingLogger):
    """Default logger that discards all metrics."""

    def log_rollout(
        self,
        *,
        global_step: int,
        rollout_id: str,
        reward: float,
        num_turns: int,
        response_length: int,
        prompt_length: int,
        latency_seconds: float,
        status: str,
        extra: Optional[dict[str, Any]] = None,
    ) -> None:
        return


class ConsoleLogger(TrainingLogger):
    """Simple console logger useful for debugging and CI."""

    def log_rollout(
        self,
        *,
        global_step: int,
        rollout_id: str,
        reward: float,
        num_turns: int,
        response_length: int,
        prompt_length: int,
        latency_seconds: float,
        status: str,
        extra: Optional[dict[str, Any]] = None,
    ) -> None:
        logger.info(
            "[step=%d] rollout=%s reward=%.4f turns=%d "
            "prompt=%d response=%d latency=%.3fs status=%s",
            global_step,
            rollout_id,
            reward,
            num_turns,
            prompt_length,
            response_length,
            latency_seconds,
            status,
        )


class TensorBoardLogger(TrainingLogger):
    """TensorBoard logger backed by ``torch.utils.tensorboard``.

    Falls back to ``tensorboard``'s standalone ``SummaryWriter`` if torch is not
    installed. Both are optional dependencies.
    """

    def __init__(self, log_dir: str, prefix: str = "arena"):
        self.prefix = prefix
        self._writer: Any = None
        self._log_dir = log_dir

    def _writer_instance(self) -> Any:
        if self._writer is None:
            try:
                from torch.utils.tensorboard import SummaryWriter
            except ImportError:
                from tensorboardX import SummaryWriter  # type: ignore[import-not-found]
            self._writer = SummaryWriter(log_dir=self._log_dir)
        return self._writer

    def log_rollout(
        self,
        *,
        global_step: int,
        rollout_id: str,
        reward: float,
        num_turns: int,
        response_length: int,
        prompt_length: int,
        latency_seconds: float,
        status: str,
        extra: Optional[dict[str, Any]] = None,
    ) -> None:
        writer = self._writer_instance()
        prefix = self.prefix
        writer.add_scalar(f"{prefix}/reward", reward, global_step)
        writer.add_scalar(f"{prefix}/num_turns", num_turns, global_step)
        writer.add_scalar(f"{prefix}/response_length", response_length, global_step)
        writer.add_scalar(f"{prefix}/prompt_length", prompt_length, global_step)
        writer.add_scalar(f"{prefix}/latency_seconds", latency_seconds, global_step)
        writer.add_scalar(
            f"{prefix}/status_success", 1.0 if status == "success" else 0.0, global_step
        )
        if extra:
            for key, value in extra.items():
                if isinstance(value, (int, float)):
                    writer.add_scalar(f"{prefix}/{key}", value, global_step)

    def log_scalar(self, key: str, value: float, step: int) -> None:
        self._writer_instance().add_scalar(key, value, step)

    def close(self) -> None:
        if self._writer is not None:
            self._writer.close()


class WandBLogger(TrainingLogger):
    """Weights & Biases logger.

    Requires ``wandb`` to be installed and initialized by the user; this logger
    only calls ``wandb.log``.
    """

    def __init__(self, prefix: str = "arena"):
        self.prefix = prefix
        self._wandb: Any = None

    def _wandb_module(self) -> Any:
        if self._wandb is None:
            import wandb  # type: ignore[import-not-found]

            self._wandb = wandb
        return self._wandb

    def log_rollout(
        self,
        *,
        global_step: int,
        rollout_id: str,
        reward: float,
        num_turns: int,
        response_length: int,
        prompt_length: int,
        latency_seconds: float,
        status: str,
        extra: Optional[dict[str, Any]] = None,
    ) -> None:
        wb = self._wandb_module()
        data: dict[str, Any] = {
            f"{self.prefix}/reward": reward,
            f"{self.prefix}/num_turns": num_turns,
            f"{self.prefix}/response_length": response_length,
            f"{self.prefix}/prompt_length": prompt_length,
            f"{self.prefix}/latency_seconds": latency_seconds,
            f"{self.prefix}/status_success": 1.0 if status == "success" else 0.0,
            "global_step": global_step,
        }
        if extra:
            for key, value in extra.items():
                if isinstance(value, (int, float)):
                    data[f"{self.prefix}/{key}"] = value
        wb.log(data)

    def log_scalar(self, key: str, value: float, step: int) -> None:
        self._wandb_module().log({key: value, "global_step": step})


class CompositeLogger(TrainingLogger):
    """Forward metrics to multiple loggers at once."""

    def __init__(self, loggers: list[TrainingLogger]):
        self.loggers = loggers

    def log_rollout(
        self,
        *,
        global_step: int,
        rollout_id: str,
        reward: float,
        num_turns: int,
        response_length: int,
        prompt_length: int,
        latency_seconds: float,
        status: str,
        extra: Optional[dict[str, Any]] = None,
    ) -> None:
        for log in self.loggers:
            try:
                log.log_rollout(
                    global_step=global_step,
                    rollout_id=rollout_id,
                    reward=reward,
                    num_turns=num_turns,
                    response_length=response_length,
                    prompt_length=prompt_length,
                    latency_seconds=latency_seconds,
                    status=status,
                    extra=extra,
                )
            except Exception as exc:
                logger.warning("Logger %s failed: %s", type(log).__name__, exc)

    def log_scalar(self, key: str, value: float, step: int) -> None:
        for log in self.loggers:
            try:
                log.log_scalar(key, value, step)
            except Exception as exc:
                logger.warning("Logger %s failed: %s", type(log).__name__, exc)

    def close(self) -> None:
        for log in self.loggers:
            try:
                log.close()
            except Exception as exc:
                logger.warning("Logger %s close failed: %s", type(log).__name__, exc)
