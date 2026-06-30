# Arena + veRL End-to-End Integration

This example shows how to use OpenAgora as veRL's agent execution and verification backend.

## Choose the Right Path

Choose one of the following paths based on your hardware and needs:

```
No GPU?
 └─> Path A: CPU Standalone Training (Recommended for Getting Started)
     - No dependency on veRL, uses a standalone PPO implementation
     - Suitable for: learning, validation, quick experiments
     - Hardware requirement: 8GB+ RAM

Have a GPU and want to use veRL?
 └─> Path B: veRL + GPU Training (Full Integration)
     - Uses veRL's FSDP + vLLM stack
     - Suitable for: large-scale training, production environments
     - Hardware requirement: 24GB+ VRAM GPU

Just want a quick preview?
 └─> Path C: Docker Compose Quick Start
     - Automatically starts all services
     - Suitable for: demos, understanding the architecture
     - Note: not suitable for actual training
```

---

## Path A: CPU Standalone Training (Recommended for Getting Started)

**Use Cases**:
- ✅ No GPU, but want to experience RL training
- ✅ Quickly validate agent logic
- ✅ Learn and understand how Arena works
- ❌ Not suitable for large-scale training (slow)

**Prerequisites**:
- Docker
- Ollama (with `qwen3.5:0.8b` installed)
- 8GB+ RAM

**Steps**:
```bash
# 1. Start Arena Server
./bin/openagora-server

# 2. Start Ollama
ollama serve

# 3. Run CPU training
cd examples/verl-integration
python train_cpu.py
```

---

## Path B: veRL + GPU Training (Full Integration)

**Use Cases**:
- ✅ Have a GPU and need actual training
- ✅ Need to use veRL's distributed training capabilities
- ✅ Production environment deployment
- ❌ Not suitable for environments without GPU

**Prerequisites**:
- At least 1 GPU (24GB+ VRAM)
- CUDA 11.8+
- veRL installed (`pip install verl`)
- vLLM or SGLang installed

**Steps**:
```bash
# 1. Start Arena Server
./bin/openagora-server

# 2. Start vLLM
vllm serve Qwen/Qwen3.5-0.8B --enable-auto-tool-choice

# 3. Start Ray cluster (only needed for the legacy RayPPOTrainer)
ray start --head

# 4. Run veRL training
cd examples/verl-integration

# Recommended: TransferQueue-based sync trainer (production, decouples rollout and training)
python train_grpo_arena_sync.py --config-name=grpo_arena

# Or use the legacy RayPPOTrainer (main_ppo.py)
python train_grpo_arena.py --config-name=grpo_arena
```

### Sync trainer vs legacy trainer

| Entry point | veRL trainer | When to use |
|---|---|---|
| `train_grpo_arena_sync.py` | `main_ppo_sync` | Production / multi-GPU / variable rollout latency |
| `train_grpo_arena.py` | `main_ppo` (RayPPOTrainer) | Legacy single-controller path |

The sync trainer uses TransferQueue to decouple rollout generation from policy
updates, which prevents slow rollouts from stalling the GPU. Before starting it,
`train_grpo_arena_sync.py` calls
`openagora_verl.install_transfer_queue_backend()` to register the OpenAgora
adapter explicitly (no monkey patching).

---

## Path C: Docker Compose Quick Start

**Use Cases**:
- ✅ Quickly understand Arena architecture
- ✅ Demonstrate to others
- ❌ Not suitable for actual training (limited resources)
- ❌ Not suitable for long-running use (container restart will lose state)

**Notes**:
- The trainer launched by this path is a simplified version for demonstration only
- If actual training is needed, use Path A or B

```bash
cd examples/verl-integration
docker compose up --build
```

This will start:
- Ollama (LLM backend)
- Arena Server
- Ray Head
- CPU Trainer (simplified version)

**Note**: This is just a demo pipeline, not suitable for large-scale training.

---

## FAQ

### Q1: I only have a CPU, which path should I use?

**A**: Use **Path A** (CPU standalone training). `train_cpu.py` is a PPO implementation specifically optimized for CPU environments and does not depend on veRL's GPU components.

### Q2: What is the difference between Path B and Path C?

**A**:
- **Path B** is the full veRL integration, using FSDP distributed training and vLLM inference, suitable for large-scale GPU training.
- **Path C** is a simplified Docker Compose deployment, only for demonstrating the architecture, not suitable for actual training.

### Q3: Why is Path C not suitable for actual training?

**A**:
- The trainer container in Docker Compose has limited resources (default 2 CPU + 4GB RAM)
- No persistent storage, checkpoints are lost when containers restart
- Lacks GPU support, training speed is extremely slow

### Q4: I want to quickly verify agent logic locally, what should I do?

**A**:
1. Use **Path A** (CPU training)
2. Reduce training iterations: `export NUM_ITERATIONS=2`
3. Use a small model: `export MODEL_NAME=TinyLlama/TinyLlama-1.1B-Chat-v1.0`

### Q5: How much VRAM does Path B need?

**A**:
- Minimum configuration: 24GB VRAM (e.g., RTX 4090)
- Recommended configuration: 40GB+ VRAM (e.g., A100)
- If VRAM is insufficient, you can try:
  - Reduce batch size: `export BATCH_SIZE=1`
  - Use a smaller model: `export MODEL_NAME=Qwen/Qwen2.5-0.5B-Instruct`
  - Enable gradient checkpointing

### Q6: Should I use `train_grpo_arena.py` or `train_grpo_arena_sync.py`?

**A**:
- Use `train_grpo_arena_sync.py` for production or when rollout latency varies
  (it decouples rollout and training via TransferQueue).
- Use `train_grpo_arena.py` only if your veRL version does not have
  `main_ppo_sync` or you need the legacy single-controller path.
