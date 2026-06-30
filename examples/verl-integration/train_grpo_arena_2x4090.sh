#!/bin/bash
set -euo pipefail

# Arena + veRL GRPO Training on 2×RTX 4090
# ==========================================
# This launcher matches the validated configuration from 2026-06-27:
#   - External vLLM V1 backend on GPU 0 (:8001)
#   - veRL GRPO training on GPU 1 using the TransferQueue-based sync trainer
#   - Qwen/Qwen2.5-0.5B-Instruct
#   - torch.compile disabled (Triton SIGSEGV workaround on RTX 4090)
#   - use_remove_padding=False (avoids nested-tensor / TensorDict issues with TQ)
#
# Prerequisites:
#   1. Arena server running on ARENA_ENDPOINT (default localhost:9090)
#   2. vLLM server running on GPU 0:
#        CUDA_VISIBLE_DEVICES=0 vllm serve Qwen/Qwen2.5-0.5B-Instruct \
#          --port 8001 --dtype bfloat16 --enforce-eager \
#          --gpu-memory-utilization 0.85 --max-model-len 2048
#   3. Agent Docker image built: openagora-agent-minimal:latest
#   4. train.parquet / test.parquet generated in data/
#   5. openagora_verl installed; the launcher calls train_grpo_arena_sync.py,
#      which explicitly installs the TransferQueue adapter via
#      openagora_verl.install_transfer_queue_backend()
#   6. veRL installed with main_ppo_sync trainer (veRL 0.9.0.dev+)
#
# To use the legacy RayPPOTrainer instead, override the entry point:
#   TRAINER_ENTRY_POINT=./train_grpo_arena.py bash train_grpo_arena_2x4090.sh

# --- Arena Configuration ---
export ARENA_ENDPOINT="${ARENA_ENDPOINT:-localhost:9090}"
export ARENA_AGENT_IMAGE="${ARENA_AGENT_IMAGE:-openagora-agent-minimal:latest}"
export ARENA_LLM_BACKEND="${ARENA_LLM_BACKEND:-http://localhost:8001/v1}"
export ARENA_LLM_MODEL="${ARENA_LLM_MODEL:-Qwen/Qwen2.5-0.5B-Instruct}"
export ARENA_TIMEOUT_SECONDS="${ARENA_TIMEOUT_SECONDS:-600}"
# The verifier is taken from the dataset's extra_info field by ArenaAgentLoop.
export ARENA_VERIFY_COMMAND="${ARENA_VERIFY_COMMAND:-true}"

# --- Workaround for RTX 4090 + nested tensor + torch.compile ---
export TORCH_COMPILE_DISABLE="${TORCH_COMPILE_DISABLE:-1}"
export VLLM_USE_V1="${VLLM_USE_V1:-1}"

# --- Offline model loading (bypass HF Hub connectivity checks in Ray workers) ---
export HF_HUB_OFFLINE="${HF_HUB_OFFLINE:-1}"
export TRANSFORMERS_OFFLINE="${TRANSFORMERS_OFFLINE:-1}"

# --- Training uses GPU 1 (GPU 0 reserved for the standalone vLLM backend) ---
export CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-1}"

# --- Training Arguments ---
TRAIN_FILES="${TRAIN_FILES:-./data/train.parquet}"
VAL_FILES="${VAL_FILES:-./data/test.parquet}"
MODEL_PATH="${MODEL_PATH:-Qwen/Qwen2.5-0.5B-Instruct}"

# Set to the sync trainer entry point so the TransferQueue adapter is
# installed explicitly and rollout/training are decoupled.
TRAINER_ENTRY_POINT="${TRAINER_ENTRY_POINT:-$(dirname "$0")/train_grpo_arena_sync.py}"

echo "Arena endpoint:     $ARENA_ENDPOINT"
echo "Agent image:        $ARENA_AGENT_IMAGE"
echo "LLM backend:        $ARENA_LLM_BACKEND"
echo "LLM model:          $ARENA_LLM_MODEL"
echo "Train files:        $TRAIN_FILES"
echo "Val files:          $VAL_FILES"
echo "Model path:         $MODEL_PATH"
echo "CUDA visible devs:  $CUDA_VISIBLE_DEVICES"
echo "TORCH_COMPILE_DISABLE=$TORCH_COMPILE_DISABLE"
echo "VLLM_USE_V1=$VLLM_USE_V1"
echo "HF_HUB_OFFLINE=$HF_HUB_OFFLINE"
echo "TRANSFORMERS_OFFLINE=$TRANSFORMERS_OFFLINE"
echo "Agent loop config:  $(dirname "$0")/arena_agent_loop.yaml"
echo "Trainer entry point: $TRAINER_ENTRY_POINT"

python3 "$TRAINER_ENTRY_POINT" \
  algorithm.adv_estimator=grpo \
  data.train_files="$TRAIN_FILES" \
  data.val_files="$VAL_FILES" \
  data.train_batch_size=8 \
  data.max_prompt_length=256 \
  data.max_response_length=512 \
  data.filter_overlong_prompts=True \
  actor_rollout_ref.model.path="$MODEL_PATH" \
  actor_rollout_ref.actor.optim.lr=1e-6 \
  actor_rollout_ref.model.use_remove_padding=False \
  actor_rollout_ref.actor.ppo_mini_batch_size=8 \
  actor_rollout_ref.actor.ppo_micro_batch_size_per_gpu=1 \
  actor_rollout_ref.actor.use_kl_loss=True \
  actor_rollout_ref.actor.kl_loss_coef=0.01 \
  actor_rollout_ref.actor.kl_loss_type=low_var_kl \
  actor_rollout_ref.model.enable_gradient_checkpointing=True \
  actor_rollout_ref.actor.fsdp_config.param_offload=False \
  actor_rollout_ref.actor.fsdp_config.optimizer_offload=False \
  actor_rollout_ref.rollout.log_prob_micro_batch_size_per_gpu=1 \
  actor_rollout_ref.rollout.tensor_model_parallel_size=1 \
  actor_rollout_ref.rollout.name=vllm \
  actor_rollout_ref.rollout.enforce_eager=True \
  actor_rollout_ref.rollout.gpu_memory_utilization=0.7 \
  actor_rollout_ref.rollout.max_model_len=2048 \
  actor_rollout_ref.rollout.n=4 \
  actor_rollout_ref.rollout.agent.default_agent_loop=arena_agent \
  actor_rollout_ref.rollout.agent.agent_loop_config_path="$(dirname "$0")/arena_agent_loop.yaml" \
  actor_rollout_ref.ref.log_prob_micro_batch_size_per_gpu=1 \
  actor_rollout_ref.ref.fsdp_config.param_offload=False \
  algorithm.use_kl_in_reward=False \
  trainer.critic_warmup=0 \
  trainer.logger=['console'] \
  trainer.n_gpus_per_node=1 \
  trainer.nnodes=1 \
  trainer.save_freq=5 \
  trainer.test_freq=1 \
  trainer.total_epochs=10 \
  "$@"
