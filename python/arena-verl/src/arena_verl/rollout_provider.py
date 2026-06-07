# Copyright 2024 Bytedance Ltd. and/or its affiliates
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import json
import logging
from typing import Any, Dict, Generator, List, Optional

import numpy as np
import torch
from tensordict import TensorDict
from torch.distributed.device_mesh import DeviceMesh
from transformers import AutoTokenizer

from verl import DataProto
from verl.utils.config import omega_conf_to_dataclass
from verl.workers.config import HFModelConfig, RolloutConfig
from verl.workers.rollout.base import BaseRollout

from arena_sdk.client import ArenaClient

logger = logging.getLogger(__name__)


class ArenaRolloutProvider(BaseRollout):
    """veRL-compatible rollout provider backed by Arena.

    This provider implements the BaseRollout interface so that veRL's
    ActorRolloutRefWorker can use Arena as the rollout engine.  It
    runs each prompt as an Arena rollout (sandbox + LLM proxy),
    captures the agent trajectory, and converts the agent's responses
    into real token IDs that can be used for PPO training.

    Usage::
        provider = ArenaRolloutProvider(
            config=rollout_config,
            model_config=hf_model_config,
            device_mesh=device_mesh,
            arena_endpoint="localhost:9090",
            sandbox_image="openhands:latest",
            llm_backend="http://localhost:8000/v1",
            verify_command="pytest -k regression",
            max_concurrent=64,
        )
        output = provider.generate_sequences(prompts=gen_batch)
    """

    def __init__(
        self,
        config: RolloutConfig,
        model_config: HFModelConfig,
        device_mesh: DeviceMesh,
        arena_endpoint: str = "localhost:9090",
        sandbox_image: str = "openhands:latest",
        llm_backend: str = "http://localhost:8000/v1",
        verify_command: Optional[str] = None,
        max_concurrent: int = 64,
        *args,
        **kwargs,
    ):
        super().__init__(config, model_config, device_mesh, *args, **kwargs)
        self.client = ArenaClient(arena_endpoint)
        self.sandbox_image = sandbox_image
        self.llm_backend = llm_backend
        self.verify_command = verify_command
        self.max_concurrent = max_concurrent
        self.config = omega_conf_to_dataclass(config)
        self.model_config: HFModelConfig = omega_conf_to_dataclass(model_config)
        self.device_mesh = device_mesh

        # ------------------------------------------------------------------
        # Tokenizer – needed to encode agent responses into real token IDs.
        # HFModelConfig contains model_path (e.g. "meta-llama/Llama-2-7b-hf").
        # ------------------------------------------------------------------
        model_path = getattr(self.model_config, "model_path", None)
        if not model_path:
            raise ValueError(
                "model_config.model_path is required to load the tokenizer. "
                "Please set model_path in your HF model config."
            )
        self.tokenizer = AutoTokenizer.from_pretrained(model_path)
        if self.tokenizer.pad_token_id is None:
            self.tokenizer.pad_token_id = self.tokenizer.eos_token_id
        self.tokenizer.padding_side = "left"  # prompts are left-padded

    # ------------------------------------------------------------------
    # Core veRL interface – generate_sequences
    # ------------------------------------------------------------------
    def generate_sequences(self, prompts: DataProto) -> DataProto:
        """Batch generate sequences via Arena rollout.

        Args:
            prompts: DataProto containing input prompts.  Expected fields:
                - ``input_ids``      : [bsz, prompt_length]
                - ``attention_mask`` : [bsz, prompt_length]
                - ``position_ids``   : [bsz, prompt_length]
                - ``non_tensor_batch["raw_prompt"]`` : list of raw prompt strings

        Returns:
            DataProto with the same fields as the native veRL rollout:
                - ``prompts``       : [bsz, prompt_length] (same as input)
                - ``responses``     : [bsz, response_length]  **real token IDs**
                - ``response_mask`` : [bsz, response_length]  1 for real tokens
                - ``input_ids``     : [bsz, prompt_length + response_length]
                - ``attention_mask``: [bsz, prompt_length + response_length]
                - ``position_ids``  : [bsz, prompt_length + response_length]
        """
        bsz = len(prompts)
        prompt_ids = prompts.batch["input_ids"]
        prompt_attn = prompts.batch.get("attention_mask", torch.ones_like(prompt_ids))
        prompt_pos = prompts.batch.get(
            "position_ids",
            (prompt_attn.cumsum(dim=1) - 1) * prompt_attn,
        )
        prompt_length = prompt_ids.shape[1]

        # ------------------------------------------------------------------
        # 1. Extract raw prompts (what the agent sees).
        #    If ``raw_prompt`` is not in the batch, fall back to decoding
        #    ``input_ids``.  This is robust but slightly slower.
        # ------------------------------------------------------------------
        raw_prompts = prompts.non_tensor_batch.get("raw_prompt", None)
        if raw_prompts is None:
            logger.warning(
                "'raw_prompt' not found in non_tensor_batch; falling back to "
                "decoding input_ids.  Consider adding raw_prompt to the dataset "
                "for faster and more accurate rollout."
            )
            raw_prompts = [
                self.tokenizer.decode(ids, skip_special_tokens=True)
                for ids in prompt_ids
            ]
        else:
            # Ensure it's a plain Python list of strings
            raw_prompts = [str(p) for p in raw_prompts]

        # ------------------------------------------------------------------
        # 2. Run Arena rollouts for every prompt in the batch.
        # ------------------------------------------------------------------
        rollout_results = self._run_rollouts(raw_prompts)

        # ------------------------------------------------------------------
        # 3. Build real response_ids and response_mask from trajectories.
        # ------------------------------------------------------------------
        response_ids, response_mask = self._build_responses(
            rollout_results, prompt_length
        )

        # ------------------------------------------------------------------
        # 4. Assemble full sequence tensors (exactly like veRL's native
        #    HFRollout / vLLMRollout).
        # ------------------------------------------------------------------
        # Prompts are already left-padded by the dataloader; keep them.
        # Responses are right-padded by _build_responses.
        response_attn = (response_ids != self.tokenizer.pad_token_id).long()
        input_ids = torch.cat([prompt_ids, response_ids], dim=1)
        attention_mask = torch.cat([prompt_attn, response_attn], dim=1)
        position_ids = (attention_mask.cumsum(dim=1) - 1) * attention_mask

        batch = TensorDict(
            {
                "prompts": prompt_ids,          # [bsz, prompt_length]
                "responses": response_ids,      # [bsz, response_length]
                "response_mask": response_mask, # [bsz, response_length]
                "input_ids": input_ids,           # [bsz, prompt_length + response_length]
                "attention_mask": attention_mask, # [bsz, prompt_length + response_length]
                "position_ids": position_ids,     # [bsz, prompt_length + response_length]
            },
            batch_size=bsz,
        )

        return DataProto(
            batch=batch,
            non_tensor_batch=prompts.non_tensor_batch,
            meta_info=prompts.meta_info,
        )

    # ------------------------------------------------------------------
    # Arena rollout execution (unchanged logic, wrapped for veRL batch)
    # ------------------------------------------------------------------
    def _run_rollouts(self, prompts: List[str]) -> List[Dict[str, Any]]:
        """Run rollouts for a batch of prompts in parallel."""
        import concurrent.futures

        cfg = getattr(self.config, "sampling", None) or {}
        if cfg is None:
            cfg = {}
        results: List[Dict[str, Any]] = []

        with concurrent.futures.ThreadPoolExecutor(
            max_workers=self.max_concurrent
        ) as executor:
            futures = {
                executor.submit(self._run_one, i, prompt, cfg): i
                for i, prompt in enumerate(prompts)
            }
            for future in concurrent.futures.as_completed(futures):
                idx = futures[future]
                try:
                    result = future.result()
                    results.append({"index": idx, **result})
                except Exception as exc:
                    logger.error("Rollout %d failed: %s", idx, exc)
                    results.append({
                        "index": idx,
                        "error": str(exc),
                        "trajectory": [],
                        "reward": 0.0,
                    })

        results.sort(key=lambda x: x["index"])
        return results

    def _run_one(self, index: int, prompt: str, sampling: Dict[str, Any]) -> Dict[str, Any]:
        """Run a single rollout and return its trajectory + reward."""
        task_id = f"batch-{index}"
        verify = {"command": self.verify_command} if self.verify_command else None

        rollout = self.client.create_rollout(
            task_id=task_id,
            image=self.sandbox_image,
            llm_backend=self.llm_backend,
            sampling=sampling,
            verify=verify,
            task_file=prompt.encode("utf-8"),
        )
        rollout_id = rollout["rollout_id"]

        info = self.client.wait(rollout_id)
        trajectory = self.client.get_trajectory(rollout_id)

        return {
            "rollout_id": rollout_id,
            "task_id": task_id,
            "status": info["status"],
            "reward": info["reward"],
            "trajectory": trajectory,
        }

    # ------------------------------------------------------------------
    # Response construction – the critical part that turns Arena trajectories
    # into real token IDs usable by veRL.
    # ------------------------------------------------------------------
    def _build_responses(
        self, rollout_results: List[Dict], prompt_length: int
    ) -> tuple[torch.Tensor, torch.Tensor]:
        """Build response_ids and response_mask from rollout trajectories.

        For each rollout, we concatenate every assistant message found in the
        trajectory and tokenize it.  The result is padded to
        ``response_length`` (from config) so that the batch is rectangular.
        """
        response_length = getattr(
            self.config, "response_length", 512
        )

        response_ids_list: List[List[int]] = []
        response_mask_list: List[List[int]] = []

        for result in rollout_results:
            if "error" in result:
                # Error case – emit a single pad token so the batch stays valid.
                response_ids_list.append([self.tokenizer.pad_token_id])
                response_mask_list.append([0])
                continue

            trajectory = result.get("trajectory", [])
            # --------------------------------------------------------------
            # Extract all assistant messages from the LLM proxy trajectory.
            # Each step in the trajectory corresponds to one LLM call; the
            # agent's response lives in ``response.content``.
            # --------------------------------------------------------------
            texts: List[str] = []
            for step in trajectory:
                resp = step.get("response") or {}
                content = resp.get("content") if isinstance(resp, dict) else None
                if content:
                    texts.append(str(content))

            full_response = "\n".join(texts) if texts else ""

            # --------------------------------------------------------------
            # Tokenize.  We do NOT add special tokens here because the
            # response is a continuation of the prompt, and veRL's loss
            # computation expects the raw generated tokens.
            # --------------------------------------------------------------
            if full_response:
                ids = self.tokenizer.encode(full_response, add_special_tokens=False)
                # Truncate to response_length so we don't exceed the model
                # capacity or break the batch shape.
                ids = ids[:response_length]
                response_ids_list.append(ids)
                response_mask_list.append([1] * len(ids))
            else:
                # Empty response – pad to a single pad token.
                response_ids_list.append([self.tokenizer.pad_token_id])
                response_mask_list.append([0])

        # --------------------------------------------------------------
        # Right-pad to response_length (consistent with veRL convention).
        # --------------------------------------------------------------
        self.tokenizer.padding_side = "right"
        padded = self.tokenizer.pad(
            [{"input_ids": ids} for ids in response_ids_list],
            padding="max_length",
            max_length=response_length,
            return_tensors="pt",
            return_attention_mask=True,
        )
        response_ids = padded["input_ids"]  # [bsz, response_length]
        response_attn = padded["attention_mask"]  # [bsz, response_length]

        # Build response_mask: 1 for real tokens, 0 for padding.
        response_mask = torch.zeros_like(response_ids)
        for i, mask in enumerate(response_mask_list):
            if len(mask) > 0:
                response_mask[i, : len(mask)] = torch.tensor(mask, dtype=torch.long)
        response_mask = response_mask * response_attn

        return response_ids, response_mask

    # ------------------------------------------------------------------
    # BaseRollout abstract methods
    # ------------------------------------------------------------------
    async def update_weights(self, weights: Generator, **kwargs):
        """Update the rollout model weights.

        For Arena, the LLM is served by a remote backend (vLLM / SGLang) and
        weights are managed externally (e.g. via the backend's weight-sync
        API).  This method is therefore a no-op, but we keep it so veRL's
        training loop does not crash.
        """
        logger.info(
            "update_weights called on ArenaRolloutProvider (no-op). "
            "Weights are managed by the remote LLM backend."
        )

    async def resume(self, tags: List[str]):
        """Resume rollout weights or kv cache in GPU memory.

        For Arena, the LLM runs remotely; this is a no-op.
        """
        pass

    async def release(self):
        """Release weights and kv cache in GPU memory.

        For Arena, the LLM runs remotely; this is a no-op.
        """
        pass

    def close(self) -> None:
        """Close the underlying Arena client."""
        self.client.close()
