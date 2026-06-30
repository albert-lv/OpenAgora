# Rollout Efficiency: Handling Variable Latency

In agent-based RL, the time needed to complete one rollout is rarely uniform.
Some prompts trigger a single LLM call and finish in seconds; others trigger
multi-turn tool use, long code generation, or expensive verification. If the
trainer waits synchronously for every rollout, the GPU sits idle while the
slowest sample finishes.

This document describes the strategies OpenAgora uses and recommends to keep
training throughput high despite variable rollout latency.

---

## 1. The Core Problem

```
Rollout 1: |████████|          (10 s)
Rollout 2: |██████████████████| (20 s)
Rollout 3: |███|                 (5 s)

Synchronous: total = 10 + 20 + 5 = 35 s, GPU idle most of the time.
Parallel:    total = max(10, 20, 5) = 20 s, but requires concurrency.
```

In veRL terms, the **rollout worker** is separate from the **policy worker**.
The rollout worker produces training samples; the policy worker consumes them.
If production is bursty, the policy worker must be fed by a buffer.

---

## 2. Strategy: Concurrent Rollouts

OpenAgora's `ArenaRollout` already uses a `ThreadPoolExecutor` to run multiple
Arena rollouts in parallel. The concurrency limit is configurable via the
`max_concurrent` parameter.

```python
# examples/verl-integration/train_grpo_arena_2x4090.sh
actor_rollout_ref.rollout.agent.default_agent_loop=arena_agent
```

When veRL's `AgentLoopManager` calls `ArenaAgentLoop.run()` once per sample,
parallelism is handled by veRL itself (it typically dispatches multiple agent
loops concurrently). When using the lower-level `ArenaRollout`, set
`max_concurrent` to a small multiple of the expected number of slow samples:

```python
rollout = ArenaRollout(
    config=...,
    max_concurrent=8,  # tune based on Arena server capacity
)
```

Rule of thumb: keep at least 2× the trainer batch size in flight so that the
trainer is never waiting for a single slow rollout.

---

## 3. Strategy: Timeouts and Partial Results

Not every rollout needs to run to completion. A hard timeout turns a
long-tailed distribution into a bounded one.

OpenAgora supports `timeout_seconds` on every rollout:

```python
self._arena.create_rollout(
    ...,
    timeout_seconds=300,  # 5 minutes max
)
```

When a rollout hits the timeout, Arena marks it as `failed` and returns the
best result gathered so far. The trainer can then:

- discard the sample,
- assign a zero or clipped reward, or
- use the partial trajectory (if it is still useful).

For GRPO, a small percentage of timeouts is acceptable because advantages are
computed within a group; one failed sample does not block the whole batch.

---

## 4. Strategy: Decouple Rollout from Training

The cleanest architecture is a **producer-consumer buffer**:

```
┌─────────────────┐      ┌──────────────┐      ┌─────────────────┐
│  Rollout Worker │─────►│  Replay/     │─────►│  Policy Worker  │
│  (Arena loops)  │      │  Transfer    │      │  (FSDP + SGD)   │
└─────────────────┘      │  Queue       │      └─────────────────┘
                         └──────────────┘
```

veRL 0.9.0.dev provides a `TransferQueue`-based replay buffer exactly for this.
When TransferQueue is installed:

1. Rollout workers push completed trajectories into the queue.
2. The trainer samples from the queue asynchronously.
3. Slow rollouts are absorbed by the buffer; the trainer keeps updating.

OpenAgora's `_patch_tq.py` ensures that the data shape produced by Arena
rollouts is compatible with veRL's TransferQueue reader. This is the
recommended path for production training.

---

## 5. Strategy: Adaptive Batch Construction

When rollouts finish at different times, a ``static`` batch size forces the
trainer to wait for the slowest straggler. Adaptive batch construction avoids
this:

- **Soft minimum batch size**: start training as soon as `N` samples are ready,
  even if the configured batch size is `N + M`.
- **Maximum wait time**: if fewer than `N + M` samples arrive within `T`
  seconds, train on whatever is available and pad/upsample to maintain DP
  divisibility.
- **Straggler mitigation**: duplicate fast samples (with appropriate weights) to
  fill the batch instead of waiting for the last rollout.

These heuristics live in the trainer, not in OpenAgora, but OpenAgora can help
by exposing per-rollout latency metrics (see `arena_rollout_duration_seconds`)
so the trainer can detect stragglers.

---

## 6. Strategy: Heterogeneous Rollout Pools

If the dataset naturally separates into easy and hard prompts, consider two
pools:

- **Fast pool**: cheap rollouts (short prompts, few tool calls).
- **Slow pool**: expensive rollouts (long reasoning, SWE-bench style).

The trainer samples proportionally from both pools, and each pool is sized to
keep its own workers busy. This avoids the situation where one hard rollout
stalls the entire batch.

---

## 7. Strategy: Token Budget Enforcement

OpenAgora's proxy enforces a per-rollout token budget (`MaxTokensBudget`). By
capping total tokens per rollout, you directly cap the worst-case latency.

```yaml
sampling:
  max_tokens_budget: 4096
```

Once the budget is exhausted, the proxy returns an error to the agent, which
can either finish early or fail gracefully. This is especially effective for
multi-turn agents that might otherwise loop forever.

---

## 8. Metrics to Watch

Use the Prometheus endpoint (`/metrics`) added to `openagora-server` to monitor
the efficiency strategies above:

| Metric | Use |
|---|---|
| `arena_rollout_duration_seconds` | Detect tail latency and tune timeouts |
| `arena_rollouts_active` | Size the rollout worker pool |
| `arena_proxy_request_duration_seconds` | Identify slow LLM backend calls |
| `arena_tokens_total` | Correlate latency with token volume |
| `arena_rollout_reward` | Check whether timeouts bias rewards |
| `arena_verify_duration_seconds` | Detect slow verification commands |

---

## 9. Recommended Default Configuration

For a single-node 2×RTX 4090 setup:

```bash
# Allow enough in-flight rollouts to absorb tail latency.
export ARENA_TIMEOUT_SECONDS=300

# Use veRL's TransferQueue so rollout and training are decoupled.
actor_rollout_ref.rollout.agent.default_agent_loop=arena_agent
actor_rollout_ref.rollout.agent.agent_loop_config_path=arena_agent_loop.yaml

# Cap per-rollout tokens to avoid runaway agents.
actor_rollout_ref.rollout.agent.sampling.max_tokens_budget=4096

# GRPO group size: keep small so a single straggler does not dominate.
actor_rollout_ref.rollout.n=4
```

---

## 10. Summary

| Strategy | Where it lives | When to use |
|---|---|---|
| Concurrent rollouts | `ArenaRollout`, veRL dispatcher | Always |
| Timeouts | `ArenaClient.create_rollout` | Always |
| TransferQueue / replay | veRL + `_patch_tq.py` | Multi-GPU / production |
| Adaptive batching | Trainer config | Highly variable latency |
| Heterogeneous pools | Dataset + sampler | Easy/hard mixed datasets |
| Token budget | Proxy sampling config | Loop-prone agents |

OpenAgora's current implementation covers the first three strategies. The next
engineering milestone is to expose enough metrics and configuration hooks so
that users can tune the remaining strategies without changing code.
