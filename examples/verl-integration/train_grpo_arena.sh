#!/bin/bash
set -euo pipefail

# Arena + veRL GRPO Training Example
# ==================================
# This script shows how to launch a veRL GRPO trainer with Arena as the
# agent execution backend.
#
# Prerequisites:
#   1. Arena server running on ARENA_ENDPOINT (default :9090)
#   2. vLLM or SGLang server running on ARENA_LLM_BACKEND
#   3. Agent Docker image available on the host
#   4. Training dataset in Parquet format

# --- Arena Configuration ---
export ARENA_ENDPOINT="${ARENA_ENDPOINT:-localhost:9090}"
export ARENA_AGENT_IMAGE="${ARENA_AGENT_IMAGE:-arena-agent-minimal:latest}"
export ARENA_LLM_BACKEND="${ARENA_LLM_BACKEND:-http://localhost:8000/v1}"
export ARENA_VERIFY_COMMAND="${ARENA_VERIFY_COMMAND:-true}"
export ARENA_TIMEOUT_SECONDS="${ARENA_TIMEOUT_SECONDS:-600}"

# Ensure arena_verl package is importable so the agent loop registers.
ARENA_VERL_SRC="$(cd "$(dirname "$0")/../../python/arena-verl/src" && pwd)"
export PYTHONPATH="${ARENA_VERL_SRC}:${PYTHONPATH:-}"

# Verify prerequisites
echo "Arena endpoint:     $ARENA_ENDPOINT"
echo "Agent image:        $ARENA_AGENT_IMAGE"
echo "LLM backend:        $ARENA_LLM_BACKEND"
echo "Verify command:     $ARENA_VERIFY_COMMAND"
echo "Arena verl src:     $ARENA_VERL_SRC"

python3 -c "import arena_verl; print('arena-verl version:', arena_verl.__doc__ or 'OK')"

# --- Training Arguments ---
# Adjust these to match your dataset, model, and cluster.
TRAIN_FILES="${TRAIN_FILES:-./data/train.parquet}"
VAL_FILES="${VAL_FILES:-./data/test.parquet}"
MODEL_PATH="${MODEL_PATH:-Qwen/Qwen2.5-7B-Instruct}"

python3 -m verl.trainer.main_ppo \
  algorithm.adv_estimator=grpo \
  data.train_files="$TRAIN_FILES" \
  data.val_files="$VAL_FILES" \
  data.train_batch_size=32 \
  data.max_prompt_length=512 \
  data.max_response_length=1024 \
  data.filter_overlong_prompts=True \
  actor_rollout_ref.model.path="$MODEL_PATH" \
  actor_rollout_ref.actor.optim.lr=1e-6 \
  actor_rollout_ref.model.use_remove_padding=True \
  actor_rollout_ref.actor.ppo_mini_batch_size=16 \
  actor_rollout_ref.actor.ppo_micro_batch_size_per_gpu=4 \
  actor_rollout_ref.actor.use_kl_loss=True \
  actor_rollout_ref.actor.kl_loss_coef=0.01 \
  actor_rollout_ref.actor.kl_loss_type=low_var_kl \
  actor_rollout_ref.model.enable_gradient_checkpointing=True \
  actor_rollout_ref.actor.fsdp_config.param_offload=True \
  actor_rollout_ref.actor.fsdp_config.optimizer_offload=True \
  actor_rollout_ref.rollout.log_prob_micro_batch_size_per_gpu=8 \
  actor_rollout_ref.rollout.tensor_model_parallel_size=1 \
  actor_rollout_ref.rollout.name=vllm \
  actor_rollout_ref.rollout.gpu_memory_utilization=0.5 \
  actor_rollout_ref.rollout.n=4 \
  actor_rollout_ref.rollout.agent.default_agent_loop=arena_agent \
  actor_rollout_ref.ref.log_prob_micro_batch_size_per_gpu=8 \
  actor_rollout_ref.ref.fsdp_config.param_offload=True \
  algorithm.use_kl_in_reward=False \
  trainer.critic_warmup=0 \
  trainer.logger=['console'] \
  trainer.n_gpus_per_node=4 \
  trainer.nnodes=1 \
  trainer.save_freq=10 \
  trainer.test_freq=1 \
  trainer.total_epochs=1 \
  "$@"
