"""Arena-backed veRL BaseRollout implementation.

This module provides ``ArenaRollout``, a ``BaseRollout`` subclass that
delegates sequence generation to an Arena sandboxed agent. It is useful when
the "rollout" is not just LLM sampling but a full agent execution loop (e.g.
coding agent, tool-use agent) whose LLM calls are proxied through Arena.

Because Arena itself does not own the inference engine, this rollout expects
the LLM backend (e.g. vLLM, SGLang, or Ollama) to be served separately. Arena's
Proxy transparently forwards the agent's LLM requests to that backend and
captures trajectories + logprobs.

Usage::

    from openagora_verl.rollout import ArenaRollout

    rollout = ArenaRollout(
        config=rollout_config,
        model_config=model_config,
        device_mesh=device_mesh,
        arena_endpoint="localhost:9090",
        arena_agent_image="openagora-agent-minimal:latest",
        arena_llm_backend="http://localhost:8000/v1",
        openagora_verify_command="pytest -k regression",
    )
    output_dp = rollout.generate_sequences(input_dp)
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

from openagora_verl.utils import extract_response_text, extract_logprobs

try:
    import torch
except ImportError:
    torch = None  # type: ignore[assignment]

try:
    import numpy as np
except ImportError:
    np = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

# Conditional veRL imports.
try:
    from verl import DataProto
    from verl.workers.rollout.base import BaseRollout
    from tensordict import TensorDict

    _VERL_AVAILABLE = True
except ImportError:
    _VERL_AVAILABLE = False

    # Minimal stubs for type-checking / standalone usage.
    class BaseRollout:  # type: ignore[no-redef]
        def __init__(self, config=None, model_config=None, device_mesh=None, **kwargs):
            self.config = config
            self.model_config = model_config
            self.device_mesh = device_mesh

    class DataProto:  # type: ignore[no-redef]
        def __init__(self, batch=None, non_tensor_batch=None, meta_info=None):
            self.batch = batch
            self.non_tensor_batch = non_tensor_batch or {}
            self.meta_info = meta_info or {}


class ArenaRollout(BaseRollout):
    """Rollout provider that runs agent execution inside Arena sandboxes.

        Each sample in the input ``DataProto`` becomes a separate Arena rollout.
        The agent executes inside a Docker sandbox; its LLM calls are proxied
        through Arena to the configured LLM backend. After the agent finishes,
        Arena verification computes a reward. The agent's response text is
    tokenized and returned as ``responses`` in the output ``DataProto``.

        Args:
            config: veRL ``RolloutConfig`` (temperature, top_p, etc.).
            model_config: veRL ``HFModelConfig`` (model path, tokenizer info).
            device_mesh: PyTorch device mesh (unused in Arena, kept for API compat).
            arena_endpoint: gRPC endpoint of the Arena server.
            arena_agent_image: Docker image for sandboxed agents.
            arena_llm_backend: URL of the LLM backend (e.g. vLLM server).
            openagora_verify_command: Shell command to run for verification.
            arena_timeout_seconds: Max seconds to wait for a rollout.
            max_concurrent: Max parallel rollouts.
    """

    def __init__(
        self,
        config: Any,
        model_config: Any,
        device_mesh: Any,
        *,
        arena_endpoint: Optional[str] = None,
        arena_agent_image: Optional[str] = None,
        arena_llm_backend: Optional[str] = None,
        openagora_verify_command: Optional[str] = None,
        arena_timeout_seconds: int = 3600,
        max_concurrent: int = 64,
        **kwargs,
    ):
        if _VERL_AVAILABLE:
            super().__init__(config, model_config, device_mesh, **kwargs)
        else:
            super().__init__()

        # Resolve arena settings from kwargs or env.
        self._arena_endpoint = arena_endpoint or os.environ.get(
            "ARENA_ENDPOINT", "localhost:9090"
        )
        self._agent_image = arena_agent_image or os.environ.get(
            "ARENA_AGENT_IMAGE", "openagora-agent-minimal:latest"
        )
        self._llm_backend = arena_llm_backend or os.environ.get(
            "ARENA_LLM_BACKEND", "http://localhost:8000/v1"
        )
        self._verify_command = openagora_verify_command or os.environ.get(
            "ARENA_VERIFY_COMMAND", "true"
        )
        self._timeout_seconds = arena_timeout_seconds
        self._max_concurrent = max_concurrent

        # Tokenizer / model references from model_config.
        self._tokenizer: Any = None
        if hasattr(model_config, "tokenizer") and model_config.tokenizer is not None:
            self._tokenizer = model_config.tokenizer
        elif hasattr(model_config, "path"):
            # Lazy-load tokenizer from HF path.
            try:
                from transformers import AutoTokenizer

                self._tokenizer = AutoTokenizer.from_pretrained(
                    model_config.path, trust_remote_code=True
                )
            except Exception as exc:
                logger.warning(
                    "Failed to load tokenizer from %s: %s",
                    getattr(model_config, "path", None),
                    exc,
                )

        if self._tokenizer is None:
            raise RuntimeError(
                "ArenaRollout requires a tokenizer. Pass it via model_config.tokenizer or model_config.path."
            )

        # Lazy-init Arena client.
        self._client: Any = None

        logger.info(
            "ArenaRollout initialized: endpoint=%s image=%s backend=%s",
            self._arena_endpoint,
            self._agent_image,
            self._llm_backend,
        )

    # ------------------------------------------------------------------
    # BaseRollout abstract methods (no-op for Arena because we don't
    # manage GPU weights directly — the LLM backend does).
    # ------------------------------------------------------------------
    async def resume(self, tags: list[str]):
        """No-op: Arena does not manage GPU KV cache or weights."""
        pass

    async def update_weights(self, weights, **kwargs):
        """No-op: weight updates go to the separate LLM backend."""
        pass

    async def release(self):
        """No-op: release any held resources."""
        pass

    # ------------------------------------------------------------------
    # Core generation
    # ------------------------------------------------------------------
    def generate_sequences(self, prompts: DataProto) -> DataProto:
        """Run Arena rollouts for a batch of prompts.

        Input ``DataProto`` is expected to contain at minimum:
        - ``batch['input_ids']``  (bsz, prompt_length)
        - ``batch['attention_mask']``
        - ``batch['position_ids']``
        - ``meta_info['eos_token_id']``

        Output ``DataProto`` contains:
        - ``batch['input_ids']``  — original prompts
        - ``batch['responses']``  — generated response token IDs
        - ``batch['sequences']``  — prompt + response concatenated
        - ``batch['attention_mask']`` — updated mask
        - ``batch['position_ids']`` — updated position IDs
        - ``batch['response_mask']`` — 1 for real response tokens, 0 for padding
        - ``batch['old_log_probs']`` — per-token logprobs (padding masked to 0)
        - ``batch['token_level_rewards']`` — per-response-token reward broadcast
        - ``non_tensor_batch['raw_prompt']`` — original text prompts
        - ``non_tensor_batch['arena_reward']`` — verification rewards
        """
        if not _VERL_AVAILABLE:
            raise RuntimeError("veRL is not installed; ArenaRollout requires verl.")

        from openagora_sdk.client import ArenaClient
        from concurrent.futures import ThreadPoolExecutor

        if self._client is None:
            self._client = ArenaClient(self._arena_endpoint)

        input_ids = prompts.batch["input_ids"]
        attention_mask = prompts.batch["attention_mask"]
        batch_size = input_ids.shape[0]
        prompt_length = input_ids.shape[1]

        # Decode each prompt to text.
        prompt_texts = []
        for i in range(batch_size):
            ids = input_ids[i][attention_mask[i].bool()].tolist()
            text = self._tokenizer.decode(ids, skip_special_tokens=True)
            prompt_texts.append(text)

        # Extract sampling params from config.
        temperature = getattr(self.config, "temperature", 1.0)
        top_p = getattr(self.config, "top_p", 1.0)
        seed = getattr(self.config, "seed", 0)
        response_length = getattr(self.config, "response_length", 512)
        n = getattr(self.config, "n", 1)  # n>1 sampling for GRPO.
        if n < 1:
            n = 1

        sampling_cfg = {"temperature": temperature, "top_p": top_p, "seed": seed}

        # Build expanded list of (original_index, prompt_text) pairs for n>1.
        tasks: list[tuple[int, str]] = []
        for i, text in enumerate(prompt_texts):
            for _ in range(n):
                tasks.append((i, text))

        # Run rollouts in parallel.
        raw_results: list[dict[str, Any]] = []
        with ThreadPoolExecutor(max_workers=self._max_concurrent) as executor:
            futures = {}
            for task_idx, (orig_idx, text) in enumerate(tasks):
                key = (orig_idx, task_idx)
                futures[
                    executor.submit(
                        self._run_one,
                        orig_idx,
                        text,
                        sampling_cfg,
                        response_length,
                        task_idx,
                    )
                ] = key

            for future in futures:
                orig_idx, task_idx = futures[future]
                try:
                    result = future.result()
                except Exception as exc:
                    logger.exception(
                        "Rollout %d sample %d failed: %s", orig_idx, task_idx, exc
                    )
                    result = self._empty_result(response_length)
                raw_results.append(
                    {
                        "orig_index": orig_idx,
                        "sample_index": task_idx,
                        **result,
                    }
                )

        # Group by original index and flatten into results list.
        results: list[dict[str, Any]] = []
        for i in range(batch_size):
            samples = [r for r in raw_results if r["orig_index"] == i]
            samples.sort(key=lambda x: x["sample_index"])
            for s in samples:
                results.append(s)

        # Assemble output tensors.
        # When n>1, results length = batch_size * n.
        out_batch_size = batch_size * n
        response_ids_list = [r["response_ids"] for r in results]
        log_probs_list = [r["log_probs"] for r in results]
        rewards = [r["reward"] for r in results]

        # Pad responses to response_length and build response masks.
        pad_token_id = self._tokenizer.pad_token_id or 0
        padded_responses = []
        padded_log_probs = []
        response_masks = []
        for r_ids, lp in zip(response_ids_list, log_probs_list):
            real_len = len(r_ids)
            pad_len = response_length - real_len
            # Clamp to response_length to avoid overflow.
            real_len = min(real_len, response_length)
            r_ids = r_ids[:response_length]
            mask = [1] * real_len + [0] * (response_length - real_len)
            if pad_len > 0:
                r_ids = r_ids + [pad_token_id] * pad_len
            if lp is not None:
                lp = lp[:response_length]
                if pad_len > 0:
                    # Padding logprobs are masked out; 0.0 is a neutral value
                    # that will be ignored because response_mask is 0 there.
                    lp = lp + [0.0] * pad_len
            else:
                lp = [0.0] * response_length
            padded_responses.append(r_ids)
            padded_log_probs.append(lp)
            response_masks.append(mask)

        responses_tensor = torch.tensor(padded_responses, dtype=torch.long)
        response_mask_tensor = torch.tensor(response_masks, dtype=torch.long)
        log_probs_tensor = torch.tensor(padded_log_probs, dtype=torch.float32)

        # Expand input tensors to match n>1 output batch size.
        if n > 1:
            input_ids_expanded = input_ids.repeat_interleave(n, dim=0)
            attention_mask_expanded = attention_mask.repeat_interleave(n, dim=0)
        else:
            input_ids_expanded = input_ids
            attention_mask_expanded = attention_mask

        sequences_tensor = torch.cat([input_ids_expanded, responses_tensor], dim=1)

        # Update attention mask and position ids for the full sequence.
        seq_len = sequences_tensor.shape[1]
        full_attention_mask = torch.zeros(out_batch_size, seq_len, dtype=torch.long)
        full_attention_mask[:, :prompt_length] = attention_mask_expanded
        # Response mask: 1 for real tokens, 0 for pad.
        for i in range(out_batch_size):
            real_resp_len = min(len(response_ids_list[i]), response_length)
            full_attention_mask[i, prompt_length : prompt_length + real_resp_len] = 1

        full_position_ids = (
            torch.arange(seq_len).unsqueeze(0).expand(out_batch_size, seq_len)
        )

        # Broadcast scalar reward to every response token.
        rewards_tensor = torch.tensor(rewards, dtype=torch.float32).unsqueeze(1)
        token_level_rewards = rewards_tensor.expand(
            out_batch_size, response_length
        ).clone()
        token_level_rewards[response_mask_tensor == 0] = 0.0

        batch = TensorDict(
            {
                "input_ids": input_ids_expanded,
                "responses": responses_tensor,
                "sequences": sequences_tensor,
                "attention_mask": full_attention_mask,
                "position_ids": full_position_ids,
                "response_mask": response_mask_tensor,
                "old_log_probs": log_probs_tensor,
                "token_level_rewards": token_level_rewards,
            },
            batch_size=out_batch_size,
        )

        # Expand non-tensor batch for n>1.
        expanded_prompts = []
        expanded_rewards = []
        expanded_status = []
        for i in range(batch_size):
            for j in range(n):
                idx = i * n + j
                expanded_prompts.append(prompt_texts[i])
                expanded_rewards.append(rewards[idx] if idx < len(rewards) else 0.0)
                expanded_status.append(
                    results[idx]["status"] if idx < len(results) else "unknown"
                )

        non_tensor_batch = {
            "raw_prompt": np.array(expanded_prompts, dtype=object),
            "arena_reward": np.array(expanded_rewards, dtype=object),
            "arena_status": np.array(expanded_status, dtype=object),
        }

        return DataProto(
            batch=batch, non_tensor_batch=non_tensor_batch, meta_info=prompts.meta_info
        )

    def _run_one(
        self,
        index: int,
        prompt_text: str,
        sampling: dict[str, Any],
        response_length: int,
        sample_index: int = 0,
    ) -> dict[str, Any]:
        """Run a single Arena rollout and tokenize the result."""
        import json

        task_payload = json.dumps(
            {
                "task_id": f"rollout-{index}-{sample_index}",
                "prompt": prompt_text,
            }
        ).encode("utf-8")

        rollout_info = self._client.create_rollout(
            task_id=f"rollout-{index}-{sample_index}",
            image=self._agent_image,
            llm_backend=self._llm_backend,
            sampling=sampling,
            verify={"command": self._verify_command} if self._verify_command else None,
            task_file=task_payload,
            timeout_seconds=self._timeout_seconds,
        )
        rollout_id = rollout_info["rollout_id"]

        result = self._client.wait(rollout_id, timeout=self._timeout_seconds)
        trajectory = self._client.get_trajectory(rollout_id)

        # Extract response text from trajectory.
        response_text = extract_response_text(trajectory)

        # Tokenize response.
        response_ids = self._tokenizer.encode(response_text, add_special_tokens=False)
        # Truncate if too long.
        if len(response_ids) > response_length:
            response_ids = response_ids[:response_length]

        # Extract logprobs.
        log_probs = extract_logprobs(trajectory, len(response_ids))

        return {
            "response_ids": response_ids,
            "log_probs": log_probs,
            "reward": float(result.get("reward", 0.0)),
            "status": result.get("status", "unknown"),
            "rollout_id": rollout_id,
        }

    def _empty_result(self, response_length: int) -> dict[str, Any]:
        """Return an empty result for failed rollouts."""
        return {
            "response_ids": [],
            "log_probs": [0.0] * response_length,
            "reward": 0.0,
            "status": "failed",
            "rollout_id": "",
        }

    def _extract_response_text(self, trajectory: list[dict[str, Any]]) -> str:
        """Extract agent response text from an Arena trajectory."""
        return extract_response_text(trajectory)

    def _extract_logprobs(
        self, trajectory: list[dict[str, Any]], response_length: int
    ) -> list[float]:
        """Extract per-token logprobs from an Arena trajectory."""
        return extract_logprobs(trajectory, response_length)
