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
| `DockerProvider.WaitForDone` | 500 ms | sandbox done file / container exit |
| `ArenaClient.wait` | 1 s | rollout status transition |
| `StreamTrajectory` | N/A | reads whole JSONL after rollout finishes |

Fast agents still pay average 250 ms sandbox poll latency and up to 1 s trainer poll latency.

### 2.4 Verification blocks rollout completion

Verification runs inside the lifecycle goroutine **before** the rollout is marked finished. A 30-second `pytest` keeps the rollout "running", so the trainer cannot consume it.

### 2.5 Trajectory backend is not throughput-oriented

- `LocalJSONL.Write` opens/appends/closes the file **on every LLM step**.
- `GetTrajectory` / `StreamTrajectory` read the full JSONL into memory and decode it; the trainer currently uses `GetTrajectory`.
- No support for batched reads or columnar formats (Parquet) needed for large-scale training.

### 2.6 Proxy-level timeout mismatch

The proxy uses a hard 120 s HTTP client timeout (`proxy.go:73`). Multi-turn agents or long code generations can be killed even when the rollout timeout is larger.

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

| # | Change | File(s) | Expected impact |
|---|---|---|---|
| A1 | **Shared proxy listener**: one `http.Server` per ArenaServer, route by rollout token. | `go/pkg/server/server.go`, `go/pkg/proxy/proxy.go` | Removes per-rollout port allocation and goroutine churn; cleaner shutdown. |
| A2 | **Event-driven sandbox completion**: replace 500 ms polling with `docker events` stream or SDK wait API. | `go/pkg/sandbox/docker/docker.go` | Cuts fast-agent tail latency by ~250 ms on average. |
| A3 | **Reduce trainer poll interval**: default from 1 s to 200 ms, and support server-sent / gRPC streaming status. | `python/openagora-sdk/src/openagora_sdk/client.py` | Faster trainer reaction; less idle GPU time. |
| A4 | **Async verification**: run verify after sandbox stops OR mark rollout success as soon as agent done and stream verification result later. | `go/pkg/server/server.go` | Trainer can consume rollout immediately; verification becomes parallelizable. |
| A5 | **Buffered trajectory writer**: keep file handle open per rollout, flush periodically. | `go/pkg/trajectory/backend/local.go` | Reduces syscall overhead for multi-turn agents. |
| A6 | **Configurable proxy timeout**: expose `Proxy.Client.Timeout` / env var so long calls are not capped at 120 s. | `go/pkg/proxy/proxy.go` | Prevents spurious failures for long reasoning/generation. |

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

*Generated during OpenAgora review, 2026-07-04.*
