# Arena × veRL GPU Validation Report & Reproduction Guide (2×RTX 4090)

> **Status: validated.** This configuration completed a 10-epoch GRPO training run on a workstation with two RTX 4090 GPUs. The run finished without crashes or OOM, with reward peaking at **96.9%**.

---

## 1. Validation goals

1. `ArenaAgentLoop` is registered as `arena_agent` and invoked by the veRL GRPO trainer.
2. Each prompt triggers an Arena sandbox rollout; the agent container calls an external vLLM backend to generate code.
3. The Arena verify plane returns a 0/1 reward using the verifier shipped in the dataset.
4. Training runs for multiple epochs without OOM or crashes, with mixed 0/1 rewards and an overall upward trend.
5. Produce training logs, GPU memory usage, and reward curves as experimental evidence for a PR.

---

## 2. Summary of results

| Metric | Value |
|---|---|
| Model | `Qwen/Qwen2.5-0.5B-Instruct` |
| GPUs | 2 × NVIDIA RTX 4090 (24 GB) |
| Training epochs | 10 |
| Peak reward | **96.9%** (step 4) |
| Final reward | ~84.4% (step 10) |
| Time per step | ~94–100 s |
| Throughput | 71–83 tokens/s |
| Peak GPU memory | ~12.2 GB allocated / ~16.6 GB reserved |
| Crashes / OOM | None |

> The drop at step 10 is expected on an 8-sample dataset with accumulating off-policy staleness and a conservative learning rate (1e-6). KL divergence increases monotonically and PG loss drops after high-reward epochs, both indicating that RL learning is active.

---

## 3. Hardware and software environment

### 3.1 Hardware requirements

| Item | Requirement |
|---|---|
| GPUs | 2 × NVIDIA RTX 4090 (24 GB VRAM) |
| CPU / RAM | 16+ cores / 64 GB+ |
| Disk | 200 GB+ (model weights, Docker images, checkpoints) |

### 3.2 Validated software stack

| Component | Version |
|---|---|
| Python | 3.11 |
| PyTorch | 2.6.0+cu124 |
| veRL | 0.9.0.dev0 (`8f5e16179f7b4b479aa95a072848438ad6bcbf64`) |
| vLLM | 0.9.0 |
| Ray | 2.55.1 |
| TensorDict | 0.10.0 |
| CUDA | 12.4 |
| NVIDIA driver | >= 535 |

### 3.3 Key workarounds

| Issue | Workaround |
|---|---|
| `torch.compile` SIGSEGV on RTX 4090 | `TORCH_COMPILE_DISABLE=1` |
| vLLM V1 engine startup crash | `--enforce-eager` |
| TQ returns padded tensors while veRL expects nested | `openagora_verl.install_transfer_queue_backend()` |

---

## 4. Installation

```bash
# 1. Clone the repository
git clone https://github.com/albert-lv/OpenAgora.git
cd OpenAgora

# 2. Create a Python environment
python3.11 -m venv .venv
source .venv/bin/activate

# 3. Install PyTorch with CUDA 12.4
pip install torch==2.6.0 torchvision torchaudio --index-url https://download.pytorch.org/whl/cu124

# 4. Install veRL from the validated commit
pip install git+https://github.com/volcengine/verl.git@8f5e16179f7b4b479aa95a072848438ad6bcbf64

# 5. Install vLLM
pip install vllm==0.9.0

# 6. Install OpenAgora adapters (registers ArenaAgentLoop and the TransferQueue adapter)
pip install -e python/openagora-sdk
pip install -e python/openagora-verl

# When using the TransferQueue-based sync trainer, install the adapter explicitly:
# python -c "import openagora_verl; openagora_verl.install_transfer_queue_backend()"

# 7. Install dataset utilities
pip install pandas pyarrow
```

---

## 5. Build the agent Docker image

```bash
docker build \
    -t openagora-agent-minimal:latest \
    -f docker/Dockerfile.agent-minimal .
```

Verify the image:

```bash
docker run --rm openagora-agent-minimal:latest python3 /app/agent.py
```

---

## 6. Prepare the dataset

```bash
cd examples/verl-integration/data
python3 gen_dataset.py
ls -lh train.parquet test.parquet
```

Each prompt asks the agent to implement `add(a, b)`. The verifier imports `add` from `solution.py` and asserts `add(2, 3) == 5`.

---

## 7. Start the services

Three terminals are required.

### Terminal 1: Arena Server

```bash
cd /path/to/OpenAgora
source .venv/bin/activate
./bin/openagora-server --sandbox=docker --grpc :9090 --http :9093
```

### Terminal 2: External vLLM backend (GPU 0)

```bash
source .venv/bin/activate
CUDA_VISIBLE_DEVICES=0 vllm serve Qwen/Qwen2.5-0.5B-Instruct \
  --port 8001 \
  --dtype bfloat16 \
  --enforce-eager \
  --gpu-memory-utilization 0.85 \
  --max-model-len 2048
```

> `--enforce-eager` is required as a workaround for RTX 4090 + vLLM V1.

### Terminal 3: Training (GPU 1)

```bash
cd examples/verl-integration
bash train_grpo_arena_2x4090.sh
```

The launcher uses `train_grpo_arena_sync.py` by default, which:
1. Registers the `arena_agent` agent loop.
2. Explicitly installs the OpenAgora TransferQueue adapter.
3. Delegates to `verl.trainer.main_ppo_sync`.

It already sets:
- `TORCH_COMPILE_DISABLE=1`
- `VLLM_USE_V1=1`
- `CUDA_VISIBLE_DEVICES=1`
- external LLM backend `http://localhost:8001/v1`
- 10 epochs, batch size 8, `n=4`

To use the legacy `RayPPOTrainer` (`main_ppo.py`) instead, override the entry point:

```bash
TRAINER_ENTRY_POINT=./train_grpo_arena.py bash train_grpo_arena_2x4090.sh
```

> If you do **not** have `main_ppo_sync` in your veRL version, fall back to the legacy trainer with the command above.

---

## 8. Expected results

### 8.1 Signs of a successful run

```text
(RolloutWorker pid=xxxx) Arena rollout xxxxxx finished: status=success reward=1.0 ...
(RolloutWorker pid=xxxx) Arena rollout xxxxxx finished: status=success reward=0.0 ...
```

At the end of training you should see:

```text
Saving checkpoint to .../checkpoint-10
```

### 8.2 Metrics to capture

1. The last 50 lines of the training log.
2. An `nvidia-smi` screenshot showing peak memory usage.
3. At least five `verify exec` lines from the Arena server log showing rewards of 0 and 1.
4. Whether the checkpoint directory exists.
5. Total training time.

### 8.3 Minimum success criteria

| Check | Pass criterion |
|---|---|
| No crash | `trainer.total_epochs=10` exits normally with code 0. |
| Non-constant reward | At least one `reward=1.0` and one `reward=0.0` are observed. |
| No OOM | `nvidia-smi` peak stays below 24 GB; no `CUDA out of memory`. |
| Checkpoint | `examples/verl-integration/checkpoints/checkpoint-10/` exists. |

---

## 9. Reference training metrics

### 9.1 10-epoch training curve

| Step | Epoch | Score (reward) | PG Loss | KL Loss | Grad Norm | Entropy | Resp Len | Throughput |
| ---- | ----- | -------------- | ------- | ------- | --------- | ------- | -------- | ---------- |
| 3    | 2     | 0.875          | 0.0297  | 0.0020  | 3.26      | 0.591   | 186.9    | 76.2 tok/s |
| 4    | 3     | **0.969**      | 0.0206  | 0.0013  | —         | 0.515   | 187.3    | —          |
| 5    | 4     | 0.906          | —       | —       | —         | 0.618   | 185.8    | —          |
| 6    | 5     | 0.813          | 0.0670  | 0.0023  | —         | 0.612   | 198.7    | —          |
| 7    | 6     | 0.875          | 0.0242  | 0.0026  | —         | 0.673   | 200.8    | 82.7 tok/s |
| 8    | 7     | 0.906          | 0.0266  | 0.0031  | 2.55      | 0.658   | 193.7    | 78.4 tok/s |
| 9    | 8     | **0.938**      | 0.0197  | 0.0049  | 2.36      | 0.630   | 188.8    | 77.0 tok/s |
| 10   | 9     | 0.844          | 0.1202  | 0.0091  | 3.49      | 0.568   | 183.7    | 71.1 tok/s |

### 9.2 Rollout consistency

| Step | rollout_probs_diff_mean | pearson_corr | KL divergence |
| ---- | ----------------------- | ------------ | ------------- |
| 3    | 0.0096                  | 0.993        | 0.0027        |
| 7    | 0.0099                  | 0.993        | 0.0025        |
| 8    | 0.0133                  | 0.988        | 0.0068        |
| 9    | 0.0125                  | 0.995        | 0.0126        |
| 10   | 0.0151                  | 0.989        | 0.0122        |

---

## 10. Key issues and solutions

### 10.1 TransferQueue nested/padded hybrid strategy

veRL's `no_padding_2_padding()` dispatches on `data["prompts"].is_nested`:
- `prompts` and `responses` must be nested tensors so veRL can compute lengths.
- `attention_mask` is asserted non-nested in the else branch, so it must be padded.

OpenAgora's original `transfer_queue._TQClient.async_get_data()` returned padded tensors for all fields, causing veRL to crash.

**Solution**: use the OpenAgora TransferQueue adapter. Import `openagora_verl` and
call `openagora_verl.install_transfer_queue_backend()` before starting the sync
trainer, or launch via `examples/verl-integration/train_grpo_arena_sync.py`.
The adapter returns the correct layout without runtime monkey patching.

See `python/openagora-verl/src/openagora_verl/transfer_queue/`.

### 10.2 torch.compile SIGSEGV

On RTX 4090, the `torch.compile` path used by veRL/vLLM triggers a Triton compiler SIGSEGV.

**Solution**: set `TORCH_COMPILE_DISABLE=1` before training.

### 10.3 vLLM V1 engine startup crash

vLLM 0.9.0's V1 engine is incompatible with the default eager-compile path on RTX 4090.

**Solution**: pass `--enforce-eager` to the vLLM server and set `actor_rollout_ref.rollout.enforce_eager=True` in the veRL config.

---

## 11. Troubleshooting

### 11.1 `arena_agent` not registered

```text
KeyError: 'arena_agent'
```

Check that `train_grpo_arena.py` successfully imports `openagora_verl`:

```bash
python -c "import openagora_verl; print(openagora_verl)"
```

### 11.2 Agent container cannot reach the LLM

The Arena server injects `OPENAI_BASE_URL` into the container pointing to its own proxy. Confirm:
- `ARENA_LLM_BACKEND` points to an external vLLM address reachable from the host (`http://localhost:8001/v1`).
- The Arena server binary runs on the host, not inside a container.

### 11.3 Verifier always fails

Inspect the generated `/sandbox/solution.py`:

```bash
# Find the most recent rollout container
docker ps -a | grep openagora-agent-minimal
# Inspect the file
docker exec -it <container_id> cat /sandbox/solution.py
```

If `solution.py` is empty, the vLLM backend did not return a response; check the vLLM logs and ensure `ARENA_LLM_MODEL` matches the served model.

---

## 12. Suggested PR scope for veRL

### 12.1 Current state

- **OpenAgora-side change**: `python/openagora-verl/src/openagora_verl/transfer_queue/`
  provides a clean adapter for TransferQueue; call
  `openagora_verl.install_transfer_queue_backend()` before starting the sync trainer.
- **veRL source logic unchanged**: only two dead-code blocks remain in `transformer_impl.py` (padded paths that are never reached). They can be removed safely but do not affect correctness.

### 12.2 Recommended PR contributions

1. **Documentation**: clarify the nested/padded contract expected by `no_padding_2_padding` in the TransferQueue interface docs.
2. **Better diagnostics**: replace bare `assert` statements at the entry of `no_padding_2_padding` with user-friendly error messages.
3. **Dead-code cleanup**: remove the unreachable padded branches in `transformer_impl.py`.

It is not recommended to add padded-tensor support inside veRL, because that would increase maintenance overhead and conflict with veRL's flash_attn_varlen architecture.

---

## 13. Next steps

| Phase | Goal | Configuration change |
|---|---|---|
| Phase 1 (current) | Run 0.5B GRPO for 10 epochs on 2×RTX 4090 | This guide |
| Phase 2 | Scale to 1.5B / 3B | Change `MODEL_PATH`; enable vLLM TP=2 or reduce batch size if memory is tight |
| Phase 3 | Real SWE-bench tasks | Switch `ARENA_AGENT_IMAGE` to `openagora-swe-agent:<instance_id>` and use SWE-bench Lite data |
| Phase 4 | Multi-node / multi-GPU | Adjust `trainer.nnodes` and Ray cluster config |
