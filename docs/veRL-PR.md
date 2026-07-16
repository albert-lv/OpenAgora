# veRL PR Draft: OpenAgora Agent Loop Integration

This document is a living draft for the upstream PR to
[volcengine/verl](https://github.com/volcengine/verl). It maps the standalone
OpenAgora repository onto veRL's code base and provides the PR title,
description, and validation plan.

---

## PR Title

```
[rollout, doc] feat: add OpenAgora sandbox agent loop integration
```

## PR Description

### Motivation

veRL's agent-loop framework lets users run multi-turn tool-use agents during
rollout, but it lacks a built-in, language-agnostic execution plane for those
agents. Today, users either run agents in-process (unsafe and hard to
reproduce) or hand-roll their own sandbox/verification glue.

This PR adds an **OpenAgora** integration that turns veRL's agent loop into a
fully sandboxed, observable, and reward-decoupled pipeline:

- **Sandboxed execution**: agents run inside Docker containers orchestrated by
the OpenAgora server.
- **Active LLM proxy**: the OpenAgora proxy injects sampling parameters and
captures per-token logprobs, giving the trainer fine-grained control.
- **Decoupled verification**: rewards are computed by an independent verifier
plane, not by the agent itself.
- **RL-grade trajectories**: every request/response pair is stored in a
structured, append-only trajectory log.

### Design & Code Changes

1. **`verl/agent_loop/arena_agent_loop.py`** (new)
   - Subclasses `AgentLoopBase` and registers as `"arena_agent"`.
   - Encodes veRL prompts into an OpenAgora task.
   - Submits the task to the OpenAgora server and waits for completion.
   - Fetches the captured trajectory, tokenizes prompt + response, and returns
     `AgentLoopOutput` including `reward_score` from OpenAgora verification.
   - Falls back to lightweight mocks when veRL is not installed, so the module
     can be developed and unit-tested standalone.

2. **`verl/utils/arena_client.py`** (new, optional)
   - Thin gRPC client for the OpenAgora server.
   - Handles rollout creation, polling, trajectory retrieval, and logprob
     extraction.
   - Alternatively, the PR can keep this client inside the OpenAgora SDK and
     depend on a published `openagora-sdk` wheel (see open questions below).

3. **Documentation** (`docs/advance/agent_loop.rst`)
   - Adds an "OpenAgora" subsection explaining setup, environment variables,
     and launch commands.

4. **Examples** (`examples/arena_grpo/`)
   - `train_grpo_arena.py`: wrapper that imports the adapter and calls
     `verl.trainer.main_ppo` (legacy RayPPOTrainer path).
   - `train_grpo_arena_sync.py`: wrapper that installs the OpenAgora
     TransferQueue adapter and calls `verl.trainer.main_ppo_sync`.
   - `train_grpo_arena.sh`: shell launcher setting environment variables and
     Hydra overrides; defaults to the legacy entry point.
   - `train_grpo_arena_2x4090.sh`: validated 2×RTX 4090 launcher; defaults to
     the TransferQueue-based sync entry point.
   - `docker-compose.yml`: reference stack with Ollama backend.
   - `docker-compose.vllm.yml`: reference stack with vLLM backend.

### API / Usage Example

```bash
# 1. Start the OpenAgora server
./bin/openagora-server --sandbox=docker --grpc :9090 --http :9093

# 2. Start vLLM (or SGLang) as the LLM backend
vllm serve Qwen/Qwen2.5-0.5B-Instruct \
  --port 8001 --enforce-eager --dtype bfloat16

# 3. Launch GRPO training
export ARENA_ENDPOINT=localhost:9090
export ARENA_AGENT_IMAGE=openagora-agent-minimal:latest
export ARENA_LLM_BACKEND=http://localhost:8001/v1

python examples/arena_grpo/train_grpo_arena.py \
  algorithm.adv_estimator=grpo \
  actor_rollout_ref.rollout.agent.default_agent_loop=arena_agent \
  ...
```

### Experiment Validation

- [x] **CPU smoke test**: `train_cpu.py` runs end-to-end for 1 iteration on
  `Qwen/Qwen2.5-0.5B-Instruct` in the `openagora-cpu-trainer` Docker image.
  The OpenAgora server successfully orchestrated sandboxed agent rollouts,
  proxied LLM calls to Ollama, and returned rewards from the verification
  plane. Server logs show multiple rollouts with rewards 0/1 and the trainer
  exited with code 0.
- [x] **GPU GRPO test**: `train_grpo_arena_2x4090.sh` ran for 10 epochs on a
  single node with 2× RTX 4090 (24 GB). Peak reward reached **96.9%**, no
  crashes or OOM. See `docs/veRL-GPU-validation-plan-2x4090.md` for the full
  reproduction guide, software versions, and training curves.
- [x] **Unit tests**: `pytest python/openagora-verl/tests/` passes
  (31 passed, 5 skipped — the skipped tests require a local `torch`
  installation).

### Checklist

- [ ] PR title follows `[{modules}] {type}: {description}`.
- [ ] Pre-commit hooks pass (`pre-commit run --all-files`).
- [ ] Added unit tests for new code.
- [ ] Updated documentation.
- [ ] Experiment validation completed and logs attached.

---

## File Mapping: OpenAgora Repo → Upstream veRL

| OpenAgora path | Proposed upstream path | Note |
|----------------|------------------------|------|
| `python/openagora-verl/src/openagora_verl/agent_loop.py` | `verl/agent_loop/arena_agent_loop.py` | Core integration |
| `python/openagora-verl/src/openagora_verl/rollout.py` | `verl/workers/rollout/arena_rollout.py` | Optional lower-level adapter; consider omitting to keep PR focused |
| `python/openagora-verl/src/openagora_verl/transfer_queue/` | `verl/utils/arena_transfer_queue/` or keep external | Clean adapter for TransferQueue data layout |
| `python/openagora-sdk/src/openagora_sdk/client.py` | `verl/utils/arena_client.py` or keep external | gRPC client |
| `examples/verl-integration/train_grpo_arena.py` | `examples/arena_grpo/train_grpo_arena.py` | Launcher wrapper (legacy) |
| `examples/verl-integration/train_grpo_arena_sync.py` | `examples/arena_grpo/train_grpo_arena_sync.py` | Launcher wrapper (TQ sync) |
| `examples/verl-integration/train_grpo_arena.sh` | `examples/arena_grpo/train_grpo_arena.sh` | Shell launcher |
| `examples/verl-integration/README.md` | `docs/advance/agent_loop.rst` (adapted) | Documentation |

> **Note on naming:** The upstream PR can use either the "Arena" abstraction
> name or the project name "OpenAgora". We recommend keeping "Arena" as the
> abstraction (e.g. `ArenaAgentLoop`) and "OpenAgora" as the project reference
> in docs, to avoid a disruptive rename inside the trainer code.

---

## Dependency Strategy

The integration depends on the **`openagora-sdk`** package for the gRPC client.

- `openagora-verl` declares `openagora-sdk>=0.1.0` in its runtime dependencies.
- `openagora-sdk` is kept as a separate, versioned package so the protocol
  client can evolve independently of veRL's release cycle.
- For the upstream PR, the new veRL files (`ArenaAgentLoop` and optionally
  `ArenaRollout`) will import from `openagora_sdk.client` and add
  `openagora-sdk` to the veRL optional dependency group.

## Scope

- **Primary**: upstream `ArenaAgentLoop` only.
- **Optional**: keep `ArenaRollout` in the OpenAgora repository as a lower-level
  adapter. It is not required for the initial PR and can be proposed later once
  the AgentLoop integration stabilizes.

## veRL Compatibility — No Upstream Changes Required

OpenAgora does **not** require any modification to veRL, and no adaptation or
bug-fix PRs to veRL are planned: every compatibility issue found during GPU
validation is resolved on the OpenAgora side.

| Issue (veRL file) | OpenAgora-side resolution |
|---|---|
| TransferQueue returns padded tensors while the FSDP engine / v1 trainer expects nested tensors (`workers/engine/fsdp/transformer_impl.py`, `workers/engine_workers.py`) | `openagora_verl.install_transfer_queue_backend()` converts TransferQueue's padded layout into veRL's nested/padded contract inside the OpenAgora adapter (`openagora_verl.transfer_queue`); validated end-to-end on 2×RTX 4090 |
| `extra_info` arrives as a JSON string from parquet (`utils/dataset/rl_dataset.py`) | OpenAgora dataset generators write `extra_info` as a native struct column, so veRL reads it back as a dict; `ArenaAgentLoop` additionally tolerates legacy JSON strings |
| `batch.tags` / `min_global_steps` / `max_global_steps` missing (`trainer/ppo/v1/trainer_base.py`) | `ArenaAgentLoop` returns `min_global_steps` / `max_global_steps` via `AgentLoopOutput.extra_fields` |
| `rollout_log_probs` absent for agent-loop rollouts (`utils/debug/metrics.py`) | `ArenaAgentLoop` returns `response_logprobs`, which the TransferQueue path propagates as `rollout_log_probs` |
| vLLM 0.9.0 rejects `logprobs_mode` / `compilation_config` / `wait_for_requests_to_drain` (`workers/rollout/vllm_rollout/vllm_async_server.py`) | Deployment concern, not a code issue: the validated stack serves vLLM externally (`vllm serve`, pinned in `docs/veRL-GPU-validation-plan-2x4090.md`); the Arena agent loop does not drive veRL's internal vLLM server |
| flash_attn / Triton SIGSEGV on RTX 4090 | Environment workaround documented in the validation guide (`TORCH_COMPILE_DISABLE=1`) |

For deployments where TransferQueue is available, `openagora_verl` provides a
clean adapter (`openagora_verl.transfer_queue`) that converts TransferQueue's
padded tensors into the nested/padded contract veRL expects. Enable it
explicitly with:

```python
import openagora_verl
openagora_verl.install_transfer_queue_backend()
```

or launch via `examples/verl-integration/train_grpo_arena_sync.py`.

> The historical `docs/apply_verl_fixes.py` site-packages patcher (used by the
> pre-TransferQueue legacy path) has been removed; the adapter supersedes it.
> The legacy `main_ppo` entry point is kept for older veRL versions but is not
> the validated configuration.

---

### Rollout Efficiency

Variable rollout latency is addressed through concurrent rollouts, timeouts,
TransferQueue-based replay buffering, and token budgets. See
`docs/rollout-efficiency.md` for the full design and recommended tuning.

---

## Readiness Assessment (2026-06-16)

### ✅ What is already solid

| Area | Status | Evidence |
|------|--------|----------|
| Architecture | Ready | Four-plane design (rollout/proxy, sandbox, verify, trajectory) is documented and implemented in Go. |
| AgentLoop integration | Ready | `ArenaAgentLoop` subclasses `AgentLoopBase`, registers as `"arena_agent"`, and returns `AgentLoopOutput` with prompt/response IDs, logprobs, reward, and `min/max_global_steps`. |
| TransferQueue compatibility | Ready | `openagora_verl.transfer_queue` provides a clean adapter; call `install_transfer_queue_backend()` before using the sync trainer. |
| BaseRollout adapter | Ready | `ArenaRollout` implements `BaseRollout.generate_sequences`, supports `n > 1` (GRPO), and returns a `DataProto`. Considered optional for upstream. |
| gRPC client | Ready | `openagora-sdk` provides `ArenaClient` for create/wait/get/stream trajectory. |
| Metrics plane | Ready | `openagora-server` exposes Prometheus-compatible `/metrics` for rollout/proxy/verify/token metrics. |
| Experiment tracking | Ready | `openagora-verl` provides `TrainingLogger` adapters for TensorBoard, WandB, console, and composite logging. |
| Protobuf schema | Ready | `proto/openagora/v1/{arena,trajectory,sandbox}.proto` cover rollout lifecycle and trajectory storage. |
| GPU validation | Done | 10 epochs on 2×RTX 4090 with `Qwen/Qwen2.5-0.5B-Instruct`; peak reward 96.9%. |
| CPU validation | Done | `train_cpu.py` completes with local sandbox and mock LLM; checkpoint saved. |
| veRL version pin | Done | Validated against `8f5e16179f7b4b479aa95a072848438ad6bcbf64`. |
| Unit tests | Passing | `pytest python/openagora-verl/tests/` passes (31 passed, 5 skipped without local torch). |
| veRL compatibility | Ready | No veRL source changes required; the TransferQueue adapter and struct-column datasets supersede the retired `apply_verl_fixes` patcher. |
| Documentation | Ready | `docs/veRL-GPU-validation-plan-2x4090.md` has full reproduction guide and metrics. |

### ⚠️ Gaps to close before opening the PR

| Gap | Severity | Recommended Action |
|-----|----------|-------------------|
| **Upstream diff extraction** | Medium | Extract only `ArenaAgentLoop` (+ `openagora-sdk` dependency) into a patch against `volcengine/verl` and validate end-to-end. |
| **Logprob/text alignment** | Low | Covered by unit tests; document multi-turn semantics in upstream docs. |
| **Sync I/O in rollout** | Low | `ArenaRollout.generate_sequences` runs blocking gRPC calls in `ThreadPoolExecutor`. Document throughput implications; an async variant can be added later. |

### 🎯 Estimated distance

From a code-completeness standpoint, the integration is **~95% ready**. The
remaining work is almost entirely extraction:

- **0.5 day** to write upstream docs and migrate examples to the proposed
  `examples/arena_grpo/` layout.
- **1 day** to extract a minimal upstream diff (only `ArenaAgentLoop`) and
  validate it end-to-end.

Once those are done, the PR can be opened.
