#!/usr/bin/env python3
"""Apply OpenAgora compatibility patches to an installed veRL package.

This script implements the veRL-side fixes documented in
`docs/veRL-GPU-validation-plan-2x4090.md`. It does NOT modify any files in the
OpenAgora repository; it only patches the installed veRL package under the
current Python environment.

Usage:
    python docs/apply_verl_fixes.py        # apply all patches
    python docs/apply_verl_fixes.py --check # verify markers are present
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path


class Patcher:
    def __init__(self, check_only: bool = False):
        self.check_only = check_only
        self.issues: list[str] = []
        self.applied: list[str] = []

        verl_path = self._find_verl_path()
        if verl_path is None:
            raise RuntimeError(
                "Could not locate installed veRL package. "
                "Make sure you are inside the OpenAgora virtual environment."
            )
        self.verl_path = Path(verl_path)

    @staticmethod
    def _find_verl_path() -> str | None:
        spec = importlib.util.find_spec("verl")
        if spec is None or spec.origin is None:
            return None
        return str(Path(spec.origin).parent)

    def _read(self, rel_path: str) -> str:
        return (self.verl_path / rel_path).read_text(encoding="utf-8")

    def _write(self, rel_path: str, content: str) -> None:
        if self.check_only:
            return
        target = self.verl_path / rel_path
        target.write_text(content, encoding="utf-8")
        self.applied.append(rel_path)

    def _replace_once(
        self, rel_path: str, old: str, new: str, *, required: bool = True
    ) -> bool:
        content = self._read(rel_path)
        if old not in content:
            if required:
                self.issues.append(f"[{rel_path}] Could not find patch anchor")
            return False
        if content.count(old) != 1 and required:
            self.issues.append(
                f"[{rel_path}] Patch anchor is ambiguous ({content.count(old)} matches)"
            )
            return False
        self._write(rel_path, content.replace(old, new, 1))
        return True

    def fix1_vllm_api(self) -> None:
        """vLLM 0.9.0 API incompatibility."""
        rel = "workers/rollout/vllm_rollout/vllm_async_server.py"
        self._replace_once(
            rel,
            '            "logprobs_mode": self.config.logprobs_mode,\n',
            '            # "logprobs_mode": self.config.logprobs_mode,  # disabled: vLLM 0.9.0 incompatible\n',
        )
        self._replace_once(
            rel,
            '            "compilation_config": compilation_config,\n',
            '            # "compilation_config": compilation_config,  # disabled: vLLM 0.9.0 incompatible\n',
        )
        self._replace_once(
            rel,
            "    async def wait_for_requests_to_drain(self):\n        await self.engine.wait_for_requests_to_drain()\n",
            "    async def wait_for_requests_to_drain(self):\n        pass  # patched: wait_for_requests_to_drain not available in vLLM 0.9.0\n",
        )

    def fix2_extra_info_json(self) -> None:
        """Parse JSON-encoded extra_info from parquet."""
        rel = "utils/dataset/rl_dataset.py"
        self._replace_once(
            rel,
            '        if "extra_info" not in row_dict or row_dict["extra_info"] is None:\n            row_dict["extra_info"] = dict()\n',
            '        if "extra_info" not in row_dict or row_dict["extra_info"] is None:\n            row_dict["extra_info"] = dict()\n        # OpenAgora fix: parse JSON-encoded extra_info\n        if isinstance(row_dict["extra_info"], str):\n            import json as _json\n            try:\n                row_dict["extra_info"] = _json.loads(row_dict["extra_info"])\n            except _json.JSONDecodeError:\n                row_dict["extra_info"] = dict()\n',
        )

    def fix4_nontensordata_unwrap(self) -> None:
        """Unwrap NonTensorData for multi_modal_inputs."""
        rel = "workers/engine/fsdp/transformer_impl.py"
        self._replace_once(
            rel,
            '        multi_modal_inputs = extract_multi_modal_inputs(micro_batch.get("multi_modal_inputs", []))\n',
            '        _raw_mmi = micro_batch.get("multi_modal_inputs", [])\n        # OpenAgora fix: unwrap NonTensorData for text-only models\n        try:\n            from tensordict.tensorclass import NonTensorData\n            if isinstance(_raw_mmi, NonTensorData):\n                _raw_mmi = _raw_mmi.data if hasattr(_raw_mmi, "data") else []\n        except ImportError:\n            pass\n        if isinstance(_raw_mmi, list):\n            multi_modal_inputs = extract_multi_modal_inputs(_raw_mmi)\n        else:\n            multi_modal_inputs = {}\n',
        )

    def fix5_nonnested_inputs(self) -> None:
        """Non-nested tensor path in prepare_model_inputs."""
        rel = "workers/engine/fsdp/transformer_impl.py"
        old = """        else:
            if pad_mode == DatasetPadMode.NO_PADDING:
                input_ids = micro_batch["input_ids"]
                position_ids = micro_batch["position_ids"]
                pad_token_id = tu.get_non_tensor_data(data=micro_batch, key="pad_token_id", default=0)
                batch_size = micro_batch.batch_size[0]
                seq_len_effective = input_ids.offsets().diff()
                max_seq_len = int(seq_len_effective.max().item())

                input_ids_rmpad_rolled = torch.roll(input_ids.values(), shifts=-1, dims=0)
                output_args["input_ids_rmpad_rolled"] = input_ids_rmpad_rolled
                # we store the per sample temperature
                output_args["temperature"] = temperature

                input_ids = torch.nested.to_padded_tensor(
                    input_ids, padding=pad_token_id, output_size=(batch_size, max_seq_len)
                )

                if position_ids.dim() == 3:
                    position_ids = torch.nested.to_padded_tensor(
                        position_ids, padding=0, output_size=(batch_size, 4, max_seq_len)
                    ).transpose(0, 1)  # (4, batch_size, max_seq_len)
                else:
                    position_ids = torch.nested.to_padded_tensor(
                        position_ids, padding=0, output_size=(batch_size, max_seq_len)
                    )

                attention_mask = build_attention_mask_from_nested(
                    input_ids=micro_batch["input_ids"], max_seq_len=max_seq_len
                )

                model_inputs = {
                    "input_ids": input_ids,
                    "attention_mask": attention_mask,
                    "position_ids": position_ids,
                }

            else:
                raise NotImplementedError(f"pad_mode {pad_mode} not implemented")"""
        new = """        else:
            if pad_mode == DatasetPadMode.NO_PADDING:
                input_ids = micro_batch["input_ids"]
                position_ids = micro_batch["position_ids"]
                pad_token_id = tu.get_non_tensor_data(data=micro_batch, key="pad_token_id", default=0)
                batch_size = micro_batch.batch_size[0]

                if input_ids.is_nested:
                    # Original nested tensor path
                    seq_len_effective = input_ids.offsets().diff()
                    max_seq_len = int(seq_len_effective.max().item())

                    input_ids_rmpad_rolled = torch.roll(input_ids.values(), shifts=-1, dims=0)
                    output_args["input_ids_rmpad_rolled"] = input_ids_rmpad_rolled
                    # we store the per sample temperature
                    output_args["temperature"] = temperature

                    input_ids = torch.nested.to_padded_tensor(
                        input_ids, padding=pad_token_id, output_size=(batch_size, max_seq_len)
                    )

                    if position_ids.dim() == 3:
                        position_ids = torch.nested.to_padded_tensor(
                            position_ids, padding=0, output_size=(batch_size, 4, max_seq_len)
                        ).transpose(0, 1)  # (4, batch_size, max_seq_len)
                    else:
                        position_ids = torch.nested.to_padded_tensor(
                            position_ids, padding=0, output_size=(batch_size, max_seq_len)
                        )

                    attention_mask = build_attention_mask_from_nested(
                        input_ids=micro_batch["input_ids"], max_seq_len=max_seq_len
                    )
                else:
                    # Regular padded tensor path (OpenAgora fix)
                    max_seq_len = input_ids.shape[-1]
                    input_ids_flat = input_ids.reshape(-1)
                    input_ids_rmpad_rolled = torch.roll(input_ids_flat, shifts=-1, dims=0)
                    output_args["input_ids_rmpad_rolled"] = input_ids_rmpad_rolled
                    output_args["temperature"] = temperature
                    attention_mask = (input_ids != pad_token_id).long()

                model_inputs = {
                    "input_ids": input_ids,
                    "attention_mask": attention_mask,
                    "position_ids": position_ids,
                }

            else:
                raise NotImplementedError(f"pad_mode {pad_mode} not implemented")"""
        self._replace_once(rel, old, new)

    def fix6_nonnested_outputs(self) -> None:
        """Non-nested tensor path in prepare_model_outputs."""
        rel = "workers/engine/fsdp/transformer_impl.py"
        old = """                if pad_mode == DatasetPadMode.NO_PADDING:
                    cu_seqlens = input_ids.offsets()
                    seq_lengths = cu_seqlens.diff()
                    starts = torch.zeros_like(seq_lengths, dtype=torch.int64)
                    logits = torch.nested.narrow(logits, 1, starts, seq_lengths, layout=torch.jagged)
                    logits_rmpad = torch.cat([t for t in logits.unbind()])
                    input_ids_rmpad_rolled = output_args["input_ids_rmpad_rolled"]
                    log_probs = logprobs_from_logits(logits=logits_rmpad, labels=input_ids_rmpad_rolled)

                    # Mirror the use_remove_padding=True branch (see verl#6293).
                    # No Ulysses SP gather here: this branch is the no-SP path
                    # (log_probs is also not gathered) and pad_size is only
                    # populated in output_args along the use_remove_padding=True
                    # path of prepare_model_inputs.
                    if distillation_use_topk:
                        outputs = logits_processor_func(student_logits=logits_rmpad.unsqueeze(0), data=micro_batch)
                        for k, v in outputs.items():
                            v = v.squeeze(0)
                            assert v.shape == log_probs.shape, (
                                f"log_probs shape: {log_probs.shape}, {k} shape: {v.shape}"
                            )
                            model_output[k] = torch.nested.nested_tensor_from_jagged(v, cu_seqlens)

                    # (bsz, j1), for each sample, length of each sample: [real_prompt_length + real_response_length]
                    log_probs = torch.nested.nested_tensor_from_jagged(log_probs, cu_seqlens)
                    if calculate_entropy:
                        entropy = torch.nested.narrow(entropy, 1, starts, seq_lengths, layout=torch.jagged)
                        entropy_rmpad = torch.cat([t for t in entropy.unbind()])
                        entropy = torch.nested.nested_tensor_from_jagged(entropy_rmpad, cu_seqlens)
                    if calculate_sum_pi_squared:
                        sum_pi_squared = torch.nested.narrow(
                            sum_pi_squared, 1, starts, seq_lengths, layout=torch.jagged
                        )
                        sum_pi_squared_rmpad = torch.cat([t for t in sum_pi_squared.unbind()])
                        sum_pi_squared = torch.nested.nested_tensor_from_jagged(sum_pi_squared_rmpad, cu_seqlens)
                else:
                    raise NotImplementedError(f"pad_mode {pad_mode} not implemented")"""
        new = """                if pad_mode == DatasetPadMode.NO_PADDING:
                    if input_ids.is_nested:
                        # Original nested tensor path
                        cu_seqlens = input_ids.offsets()
                        seq_lengths = cu_seqlens.diff()
                        starts = torch.zeros_like(seq_lengths, dtype=torch.int64)
                        logits = torch.nested.narrow(logits, 1, starts, seq_lengths, layout=torch.jagged)
                        logits_rmpad = torch.cat([t for t in logits.unbind()])
                        input_ids_rmpad_rolled = output_args["input_ids_rmpad_rolled"]
                        log_probs = logprobs_from_logits(logits=logits_rmpad, labels=input_ids_rmpad_rolled)

                        # Mirror the use_remove_padding=True branch (see verl#6293).
                        # No Ulysses SP gather here: this branch is the no-SP path
                        # (log_probs is also not gathered) and pad_size is only
                        # populated in output_args along the use_remove_padding=True
                        # path of prepare_model_inputs.
                        if distillation_use_topk:
                            outputs = logits_processor_func(student_logits=logits_rmpad.unsqueeze(0), data=micro_batch)
                            for k, v in outputs.items():
                                v = v.squeeze(0)
                                assert v.shape == log_probs.shape, (
                                    f"log_probs shape: {log_probs.shape}, {k} shape: {v.shape}"
                                )
                                model_output[k] = torch.nested.nested_tensor_from_jagged(v, cu_seqlens)

                        # (bsz, j1), for each sample, length of each sample: [real_prompt_length + real_response_length]
                        log_probs = torch.nested.nested_tensor_from_jagged(log_probs, cu_seqlens)
                        if calculate_entropy:
                            entropy = torch.nested.narrow(entropy, 1, starts, seq_lengths, layout=torch.jagged)
                            entropy_rmpad = torch.cat([t for t in entropy.unbind()])
                            entropy = torch.nested.nested_tensor_from_jagged(entropy_rmpad, cu_seqlens)
                        if calculate_sum_pi_squared:
                            sum_pi_squared = torch.nested.narrow(
                                sum_pi_squared, 1, starts, seq_lengths, layout=torch.jagged
                            )
                            sum_pi_squared_rmpad = torch.cat([t for t in sum_pi_squared.unbind()])
                            sum_pi_squared = torch.nested.nested_tensor_from_jagged(sum_pi_squared_rmpad, cu_seqlens)
                    else:
                        # Non-nested (regular padded) path - OpenAgora fix
                        input_ids_rmpad_rolled = output_args["input_ids_rmpad_rolled"]
                        logits_flat = logits.reshape(-1, logits.shape[-1]).contiguous()
                        # Use vanilla PyTorch to avoid Triton SIGSEGV
                        from verl.utils.torch_functional import logprobs_from_logits_v2
                        log_probs = logprobs_from_logits_v2(logits=logits_flat, labels=input_ids_rmpad_rolled)
                        if calculate_entropy:
                            entropy = entropy.reshape(-1)
                        if calculate_sum_pi_squared:
                            sum_pi_squared = sum_pi_squared.reshape(-1)
                        _offsets = torch.tensor([0, log_probs.shape[0]], dtype=torch.int64, device=log_probs.device)
                        model_output["log_probs"] = torch.nested.nested_tensor_from_jagged(log_probs, _offsets)
                        if calculate_entropy:
                            model_output["entropy"] = torch.nested.nested_tensor_from_jagged(entropy, _offsets)
                        if calculate_sum_pi_squared:
                            model_output["sum_pi_squared"] = torch.nested.nested_tensor_from_jagged(
                                sum_pi_squared, _offsets
                            )
                        return model_output
                else:
                    raise NotImplementedError(f"pad_mode {pad_mode} not implemented")"""
        self._replace_once(rel, old, new)

    def fix7_train_mini_batch(self) -> None:
        """Non-nested input_ids in train_mini_batch."""
        rel = "workers/engine_workers.py"
        old = """                if "input_ids" in mini_batch_td:
                    global_token_num = mini_batch_td["input_ids"].offsets().diff().tolist()  # (total_nnz,)
                    # allgather from dp rank
                    global_token_num_output = [None] * torch.distributed.get_world_size(
                        self.engine.get_data_parallel_group()
                    )
                    torch.distributed.all_gather_object(
                        global_token_num_output, global_token_num, self.engine.get_data_parallel_group()
                    )
                    global_token_num = [x for xs in global_token_num_output for x in xs]
                else:
                    global_token_num = None"""
        new = """                if "input_ids" in mini_batch_td:
                    # OpenAgora fix: handle non-nested input_ids
                    _ids = mini_batch_td["input_ids"]
                    if hasattr(_ids, "is_nested") and _ids.is_nested:
                        global_token_num = _ids.offsets().diff().tolist()  # (total_nnz,)
                    else:
                        global_token_num = [_ids.shape[-1]] * _ids.shape[0] if _ids.dim() >= 2 else [_ids.shape[0]]
                    # allgather from dp rank
                    global_token_num_output = [None] * torch.distributed.get_world_size(
                        self.engine.get_data_parallel_group()
                    )
                    torch.distributed.all_gather_object(
                        global_token_num_output, global_token_num, self.engine.get_data_parallel_group()
                    )
                    global_token_num = [x for xs in global_token_num_output for x in xs]
                else:
                    global_token_num = None"""
        self._replace_once(rel, old, new)

    def fix8_debug_metrics(self) -> None:
        """Missing rollout_log_probs guard."""
        rel = "utils/debug/metrics.py"
        old = """    rollout_old_log_probs = data.batch["rollout_log_probs"]
    actor_old_log_probs = data.batch["old_log_probs"]"""
        new = """    # OpenAgora fix: rollout_log_probs may not exist for agent loop rollouts
    if "rollout_log_probs" not in data.batch.keys():
        return {}
    rollout_old_log_probs = data.batch["rollout_log_probs"]
    actor_old_log_probs = data.batch["old_log_probs"]"""
        self._replace_once(rel, old, new)

    def fix9_batch_tags(self) -> None:
        """Missing batch.tags guards in trainer metrics."""
        rel = "trainer/ppo/v1/trainer_base.py"
        self._replace_once(
            rel,
            '        global_seqlen_lst = torch.tensor([tag["seq_len"] for tag in batch.tags], dtype=torch.int64)\n',
            """        # OpenAgora fix: handle missing tags
        _tags3 = getattr(batch, "tags", None)
        if _tags3 is not None:
            global_seqlen_lst = torch.tensor([tag["seq_len"] for tag in _tags3], dtype=torch.int64)
        else:
            global_seqlen_lst = torch.ones(len(batch.keys), dtype=torch.int64)
""",
        )
        self._replace_once(
            rel,
            '        non_padding_mask = np.array([not tag.get("is_padding", False) for tag in batch.tags], dtype=bool)\n',
            """        # OpenAgora fix: handle missing tags attribute
        _tags = getattr(batch, "tags", None)
        if _tags is not None:
            non_padding_mask = np.array([not tag.get("is_padding", False) for tag in _tags], dtype=bool)
        else:
            non_padding_mask = np.ones(len(batch.keys), dtype=bool)
""",
        )
        old = """        min_global_steps = np.array([tag["min_global_steps"] for tag in batch.tags], dtype=int)[non_padding_mask]
        max_global_steps = np.array([tag["max_global_steps"] for tag in batch.tags], dtype=int)[non_padding_mask]"""
        new = """        # OpenAgora fix: handle missing tags
        _tags2 = getattr(batch, "tags", None)
        if _tags2 is not None:
            min_global_steps = np.array([tag["min_global_steps"] for tag in _tags2], dtype=int)[non_padding_mask]
            max_global_steps = np.array([tag["max_global_steps"] for tag in _tags2], dtype=int)[non_padding_mask]
        else:
            min_global_steps = np.zeros(non_padding_mask.sum(), dtype=int)
            max_global_steps = np.zeros(non_padding_mask.sum(), dtype=int)"""
        self._replace_once(rel, old, new)

    def run(self) -> int:
        fix_methods = [
            self.fix1_vllm_api,
            self.fix2_extra_info_json,
            self.fix4_nontensordata_unwrap,
            self.fix5_nonnested_inputs,
            self.fix6_nonnested_outputs,
            self.fix7_train_mini_batch,
            self.fix8_debug_metrics,
            self.fix9_batch_tags,
        ]
        for fix in fix_methods:
            try:
                fix()
            except Exception as exc:
                self.issues.append(f"[{fix.__name__}] {exc}")

        if self.issues:
            print("WARNINGS/ERRORS:", file=sys.stderr)
            for issue in self.issues:
                print(f"  - {issue}", file=sys.stderr)

        if self.check_only:
            if self.issues:
                print("Some markers are missing.")
                return 1
            print("All patch markers are present.")
            return 0

        if self.issues:
            print("Patching completed with warnings; review the issues above.")
            return 1

        print(f"Patched {len(self.applied)} veRL files successfully.")
        for rel in sorted(set(self.applied)):
            print(f"  - {rel}")
        return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Apply OpenAgora veRL compatibility patches"
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Only verify that patch anchors are present",
    )
    args = parser.parse_args()

    patcher = Patcher(check_only=args.check)
    return patcher.run()


if __name__ == "__main__":
    sys.exit(main())
