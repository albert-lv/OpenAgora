# OpenAgora Training Efficiency Optimization Plan

Status: **Draft / review-ready**
Scope: OpenAgora `arena-server` (Go), `openagora-sdk` / `openagora-verl` (Python), and the Code Colosseum demo trainer.

---

## 1. Current State Summary

OpenAgora is correctly decomposed into four planes:

1. **Rollout Control Plane** — Arena Proxy intercepts LLM calls, injects sampling params, enforces token budgets, records trajectories.
2. **Sandbox Plane** — Docker-based agent execution via `sandbox.Provider`.
3. **Verification Plane** — Command-based reward/verification (`verify.Runner`).
4. **Trajectory Data Plane** — JSONL backend for per-step storage and retrieval.

The data flow for one training step is:

```
Trainer (Python)
  → CreateRollout (gRPC)
    → ArenaServer starts per-rollout proxy listener + Docker sandbox
      → Agent runs inside sandbox, calls LLM via proxy
        → Proxy forwards to backend (vLLM/SGLang/Kimi API), records trajectory
      → Agent writes /sandbox/.arena/done
    → WaitForDone (poll 500 ms) + verification
  → wait/get_trajectory (poll 1 s)
→ next rollout
```

This works for demos and correctness validation but is **not yet optimized for throughput**.

---

## 2. Verified Bottlenecks

### 2.1 Heavy per-rollout overhead

- Each `CreateRollout` spins up a **dedicated HTTP listener** (`proxy.NewProxyServerWithHost`) on a random port, then closes it at teardown.
- Each rollout creates a **fresh Docker container** from scratch, including `docker pull` if not cached, temp host dir, bind mount, and removal.
- There is **no warm container pool** and no reuse of proxy listeners.

**Impact:** Even a 1-second LLM call pays 2–10 seconds of container/proxy setup on a cold machine.

### 2.2 Synchronous trainer-side dispatch

- `ArenaAgentLoop.run()` is a single `create → wait → get_trajectory` pipeline.
- `ArenaRollout.generate_sequences()` uses `ThreadPoolExecutor` but waits for **all** samples before returning any data; one straggler stalls the whole GPU step.
- Code Colosseum demo trainer loops serially over problems (`for sample in dataset[:BATCH_SIZE]`), making it the worst case.

### 2.3 Polling everywhere

| Location | Interval | What it waits for |
|---|---|---|
| `DockerProvider.WaitForDone` | 500 ms | sandbox done file / container exit (resolved by A2: event-driven `docker wait` + host-side marker stat) |
| `ArenaClient.wait` | 1 s | rollout status transition |
| `StreamTrajectory` | N/A | reads whole JSONL after rollout finishes |

Fast agents still pay average 250 ms sandbox poll latency and up to 1 s trainer poll latency.

### 2.4 Verification blocks rollout completion

Verification runs inside the lifecycle goroutine **before** the rollout is marked finished. A 30-second `pytest` keeps the rollout "running", so the trainer cannot consume it. (Resolved by A4: verification is asynchronous by default; the rollout reaches its terminal status at generation completion and reward/report are filled in afterwards.)

### 2.5 Trajectory backend is not throughput-oriented

- `LocalJSONL.Write` opens/appends/closes the file **on every LLM step**. (Resolved by A5: per-rollout buffered writer with periodic/completion flush.)
- `GetTrajectory` / `StreamTrajectory` read the full JSONL into memory and decode it; the trainer currently uses `GetTrajectory`.
- No support for batched reads or columnar formats (Parquet) needed for large-scale training.

### 2.6 Proxy-level timeout mismatch

The proxy uses a hard 120 s HTTP client timeout (`proxy.go:73`). Multi-turn agents or long code generations can be killed even when the rollout timeout is larger. (Resolved by A6: `WithHTTPTimeout` option / `ARENA_PROXY_TIMEOUT` env var; 120 s remains the default.)

### 2.7 Missing metrics

Current metrics (`metrics.go`) cover end-to-end rollout time, verify time, proxy latency, token counts, and active rollouts. Missing:

- sandbox create/start/destroy latency
- rollout queue depth and wait time
- time-to-first-token / per-token streaming latency
- trajectory write/read latency
- per-rollout token budget exhaustion rate

---

## 3. Optimization Plan

### Phase A: Quick wins (days, demo-visible)

| # | Change | File(s) | Expected impact | Status |
|---|---|---|---|---|
| A1 | **Shared proxy listener**: one `http.Server` per ArenaServer, route by rollout token. | `go/pkg/server/server.go`, `go/pkg/proxy/proxy.go` | Removes per-rollout port allocation and goroutine churn; cleaner shutdown. | Pending |
| A2 | **Event-driven sandbox completion**: replace 500 ms polling with `docker events` stream or SDK wait API. | `go/pkg/sandbox/docker/docker.go` | Cuts fast-agent tail latency by ~250 ms on average. | **Implemented** (2026-09) |
| A3 | **Reduce trainer poll interval**: default from 1 s to 200 ms, and support server-sent / gRPC streaming status. | `python/openagora-sdk/src/openagora_sdk/client.py` | Faster trainer reaction; less idle GPU time. | **Implemented** (2026-09) |
| A4 | **Async verification**: run verify after sandbox stops OR mark rollout success as soon as agent done and stream verification result later. | `go/pkg/server/server.go` | Trainer can consume rollout immediately; verification becomes parallelizable. | **Implemented** (2026-09) |
| A5 | **Buffered trajectory writer**: keep file handle open per rollout, flush periodically. | `go/pkg/trajectory/backend/local.go` | Reduces syscall overhead for multi-turn agents. | **Implemented** (2026-09) |
| A6 | **Configurable proxy timeout**: expose `Proxy.Client.Timeout` / env var so long calls are not capped at 120 s. | `go/pkg/proxy/proxy.go` | Prevents spurious failures for long reasoning/generation. | **Implemented** (2026-09) |

#### Phase A implementation notes (deviations from the original design)

- **A2**: implemented with a blocking `docker wait` CLI call in a goroutine (not the Docker SDK, avoiding a new dependency) plus a 200 ms `os.Stat` of the done marker resolved through the host-side `/sandbox` bind mount. A 2 s `docker inspect`/`docker exec` poll remains only as a safety net.
- **A4**: the gRPC contract is unchanged (no new status value). The rollout flips to its terminal status (`success`/`failed`) as soon as generation completes; verification then runs asynchronously against the still-running sandbox and `reward`/`verification_report` are filled in when done. Trainers that need the final reward should re-fetch the rollout after `wait()` returns. Opt out with `ServerConfig.SyncVerify: true`. Side effects: `arena_rollout_duration_seconds` now measures generation time (verification excluded), and sandbox stop/destroy use a background context so cleanup is not cancelled by an expired rollout timeout.
- **A5**: `LocalJSONL` keeps one open `bufio.Writer` per rollout, flushing every 2 s, when the 64 KiB buffer fills, on `Read`, on `Finalize`, and on `Close`. A new optional `backend.Finalizer` interface lets the server flush at rollout completion without changing the `Backend` interface.
- **A6**: `proxy.WithHTTPTimeout` functional option on `NewProxy` (default 120 s unchanged), plumbed through `ServerConfig.ProxyTimeout` with an `ARENA_PROXY_TIMEOUT` env-var fallback (parsed with `time.ParseDuration`).
- **A3**: implemented as adaptive polling instead of a fixed 200 ms interval — the SDK `wait()` now uses full-jitter exponential backoff (default 100 ms → 2 s cap, configurable via `poll_initial_interval` / `poll_max_interval` / `poll_backoff_multiplier`), and an `async wait_async()` counterpart was added for high-concurrency trainers. The verl adapter (`ArenaAgentLoop`) polls non-blockingly with its own backoff via `asyncio.to_thread`. Server-sent / gRPC streaming status remains a future Phase B improvement (B2).

### Phase B: Throughput-oriented features (weeks)

| # | Change | File(s) | Expected impact |
|---|---|---|---|
| B1 | **Sandbox warm pool**: pre-create and idle-warm containers; checkout on `CreateRollout`, reset and return on completion. | `go/pkg/sandbox/docker/` + new `pool.go` | Eliminates container create/start overhead; biggest single throughput win. |
| B2 | **Streaming trajectory consumption**: trainer consumes steps as they are written, not after rollout ends. | `go/pkg/proxy/proxy.go`, `python/openagora-sdk/src/openagora_sdk/client.py`, `python/openagora-verl/src/openagora_verl/agent_loop.py` | Enables early partial consumption and reduces memory. |
| B3 | **Server-side rollout queue**: bounded queue + worker pool in ArenaServer; trainer pushes requests, server controls concurrency. | `go/pkg/server/server.go` | Better backpressure, resource control, and observability. |
| B4 | **Straggler mitigation in trainer**: return partial batches; fill with duplicate fast samples or pad. | `python/openagora-verl/src/openagora_verl/rollout.py` | Reduces GPU idle time waiting for slowest rollout. |
| B5 | **Columnar trajectory backend (Parquet/S3)**: optional backend for large-scale runs. | `go/pkg/trajectory/backend/` | Better compression and batched reads for RL training. |
| B6 | **Per-step metrics**: sandbox start, queue wait, first token, verify, trajectory read/write. | `go/pkg/server/metrics.go` | Enables data-driven tuning. |

### Phase C: Production integrations (weeks–months)

| # | Change | File(s) | Expected impact |
|---|---|---|---|
| C1 | **TransferQueue integration**: connect `openagora-verl` to veRL's built-in replay/transfer queue. | `python/openagora-verl/` | Decouples rollout generation from policy updates. |
| C2 | **Multi-node rollout workers**: horizontally scale rollout workers behind ArenaServer. | `go/pkg/server/`, deployment | Supports large-scale training. |
| C3 | **Lazy policy loading for sandbox**: keep actor weights in a shared volume; avoid per-container copy. | Docker layer + `sandbox.Provider` | Reduces image size and startup time. |

---

## 4. Recommended Priority Order

1. **Shared proxy listener (A1)** — low risk, removes obvious overhead.
2. **Sandbox warm pool (B1)** — highest impact on throughput; requires careful lifecycle management.
3. **Async verification + faster trainer polling (A4 + A3)** — removes unnecessary idle waiting.
4. **Streaming trajectory (B2)** — needed for true async training.
5. **Event-driven sandbox completion (A2)** — easy follow-up after B1.
6. **Metrics (B6)** — enables tuning the remaining phases.
7. **Server-side queue (B3)** and **straggler mitigation (B4)** — production stability.

---

## 5. Suggested Success Metrics

After the plan is implemented, target:

- **Sandbox reuse rate** ≥ 80% (warm pool hit rate)
- **Average rollout overhead** (create + start + proxy) ≤ 500 ms
- **Trainer idle time due to polling** ≤ 5% of step time
- **GPU utilization** during rollout generation ≥ 70% on steady-state training
- **P99 end-to-end rollout latency** within 1.5× of agent LLM + verify time

---

## 6. Risks and Notes

- **Warm pool hygiene**: reset container filesystem and env between rollouts to avoid state leakage; use read-only base layers + tmpfs overlay.
- **Shared proxy listener**: must still isolate rollout tokens correctly; keep per-rollout backend/sampling state.
- **Async verification**: trainer must be able to receive reward updates after consuming the rollout (e.g., via `UpdateRollout` or streaming verification report).
- **Backward compatibility**: keep existing gRPC API; add new optional fields/methods rather than breaking changes.

---

## 7. Industry Alignment Review (2026-09)

A September 2026 review of mainstream RL training frameworks ([verl](https://github.com/verl-project/verl), [slime](https://github.com/THUDM/slime)/[Miles](https://radixark.mintlify.app/), [SGLang RL APIs](https://github.com/sgl-project/sglang/issues/24119), [harness-native agentic RL](https://arxiv.org/html/2608.17393)) against OpenAgora:

**Where OpenAgora now converges with industry practice**

- *Async rollout pipeline*: verl's agent-loop scheduler and async partial rollout ([verl-recipe#58](https://github.com/verl-project/verl-recipe/pull/58)) assume non-blocking per-sample rollouts. `ArenaAgentLoop.run` is now truly async (thread-offloaded gRPC + backoff polling), and the SDK offers `wait_async`, so thousands of concurrent rollouts no longer pin threads (Phase A, done 2026-09).
- *Trainer reaction latency*: fixed-interval polling (the 1 s `wait()`) is replaced by full-jitter exponential backoff (100 ms → 2 s), matching the poll behavior of modern SDKs.

**Gaps the industry has closed that OpenAgora has not** (priority order)

1. **Weight synchronization to the inference engine** — the largest gap. slime/SGLang push weights into the rollout engine every step (IPC/RDMA transfer, sleep/wake); OpenAgora's external vLLM serves stale initial weights, guaranteeing off-policy drift (`ArenaRollout.update_weights` is a no-op). Target: implement `update_weights` via the inference server's weight-reload API (vLLM `/update_weights` RL endpoint or SGLang `update_weights_from_disk`/IPC), keyed off the `min/max_global_steps` metadata the adapter already plumbs. **Implemented 2026-09**: server-side `UpdateWeights` RPC plus a `go/pkg/inference` `WeightSyncer` relay (SGLang `pause_generation` → `update_weights_from_disk` → `continue_generation`; vLLM pause/resume only — disk reload unsupported by vLLM's HTTP API), with new rollouts stamped with the served `weight_version`. Python side: SDK `ArenaClient.update_weights`/`update_weights_async`, and `ArenaRollout.update_weights` forwards the trainer's checkpoint path (`weight_sync_model_path` kwarg or `ARENA_WEIGHT_SYNC_MODEL_PATH`) plus a version to the server; the stamped `weight_version` is propagated per sample via `non_tensor_batch['arena_weight_version']` and `extra_fields`.
2. **Partial rollout (pause/resume long episodes)** — the 2026 standard for long-tail agentic rollouts ([APR](https://github.com/verl-project/verl-recipe/pull/58), [WAR](https://arxiv.org/html/2607.17299v1), [partial-rollout checkpointing](https://blog.guanghan.ai/post/260208_rl_infra/)): interrupt a long rollout, snapshot sandbox state, resume under newer weights in a later iteration. **Implemented 2026-09**: `PauseRollout`/`ResumeRollout` RPCs (freeze mode) over a new optional `sandbox.Pauser` interface (docker `pause`/`unpause`, local SIGSTOP/SIGCONT, mock no-op); the rollout timeout clock is suspended while paused and the per-rollout proxy listener survives the freeze, so resume needs no re-registration. Python side: SDK `pause_rollout`/`resume_rollout` (+ async variants) and a `return_on_pause` flag on `wait`/`wait_async` so trainers that pause stragglers don't spin until timeout. Checkpoint-restore (cross-host migration) and B3 (server-side queue) remain open.
3. **Training–inference token fidelity** — frameworks now propagate engine-native token IDs through agent loops; OpenAgora re-tokenizes response text and heuristically aligns logprobs (`openagora_verl/utils.py`), a known correctness risk. **Implemented 2026-09**: the proxy opportunistically captures engine-native token IDs (SGLang top-level/`meta_info` `prompt_token_ids`/`completion_token_ids`/`output_token_logprobs`, vLLM-style `choices[].token_ids`) into new `LLMResponse.prompt_token_ids`/`completion_token_ids`/`weight_version` proto fields; with `BackendType=vllm` configured the proxy also injects `return_tokens_as_token_ids`. Python side: `ArenaAgentLoop.run` builds `response_ids` directly from the concatenated engine-native `completion_token_ids` when present (via `openagora_verl/utils.py:extract_native_token_ids`), eliminating the re-tokenization mismatch, and records per-step `min/max_weight_version` in `extra_fields`; empty fields mean re-tokenization fallback, as before.
4. **Server-side rollout queue + straggler mitigation** (B3/B4) — still pending; aligns with the industry's workload-aware rollout scheduling direction.
5. **Streaming trajectory consumption** (B2) — `StreamTrajectory` currently reads the whole JSONL then replays it; true streaming is the prerequisite for early/partial consumption.

**Implementation notes (2026-09, items 1–3)**

- All proto changes are additive: three new RPCs, six new messages, `Rollout.weight_version = 8`, and `LLMResponse` fields 4–6; no existing field was renumbered. The Python stubs are regenerated via `make proto` and are the contract for the pending SDK/adapter work.
- `UpdateWeights` is serialized by a server-side mutex; generation is always resumed (best effort) even after a failed refit. The backend is configured via `ServerConfig.BackendType`/`BackendURL` or the `ARENA_BACKEND_TYPE`/`ARENA_BACKEND_URL` env vars; without them the RPC returns `FailedPrecondition`.
- Pause/resume works only from `running` ↔ `paused` (new status value); other transitions return `FailedPrecondition`, unknown rollout IDs `NotFound`, providers without `sandbox.Pauser` `Unimplemented`. While paused, the trajectory writer is flushed (new optional `backend.Flusher`, flush-without-close) but not finalized, and `docker wait` simply blocks through the freeze.
- Python follow-up (2026-09): SDK client methods for pause/resume/update_weights (sync + async), `return_on_pause` on `wait`/`wait_async`, verl adapter plumbing (`ArenaRollout.update_weights`), and `ArenaAgentLoop` consuming `prompt_token_ids`/`completion_token_ids` in place of re-tokenization when present.

**Deprioritized by industry evidence**: Megatron-backend support and multi-node rollout (C2) matter only at >1 node scale; OpenRLHF/slime show single-node colocated setups remain the sweet spot for arena-style agentic workloads.

---

*Generated during OpenAgora review, 2026-07-04. Phase A implemented and industry alignment reviewed 2026-09. §7 gap items 1–3 (weight sync, partial rollout, token fidelity) fully implemented 2026-09 (Go server + Python SDK/adapter).*
