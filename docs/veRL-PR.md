# veRL PR Draft: OpenAgora Agent Loop Integration

This document is a living draft for the upstream PR to
[volcengine/verl](https://github.com/volcengine/verl). It maps the standalone
OpenAgora repository onto veRL's code base and provides the PR title,
description, and validation plan.

---

## PR Title

```
[agent, rollout, doc] feat: add OpenAgora sandbox agent loop integration
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

2. **`verl/workers/rollout/arena_rollout.py`** (new, optional)
   - A `BaseRollout`-compatible adapter for users who prefer the lower-level
     rollout API over the AgentLoop framework.
   - Supports `n > 1` (GRPO-style) by expanding the batch.

3. **`verl/utils/arena_client.py`** (new, or use external SDK)
   - Thin gRPC client for the OpenAgora server.
   - Handles rollout creation, polling, trajectory retrieval, and logprob
     extraction.

4. **Documentation** (`docs/advance/agent_loop.rst`)
   - Adds an "OpenAgora" subsection explaining setup, environment variables,
     and launch commands.

5. **Examples** (`examples/arena_grpo/`)
   - `train_grpo_arena.py`: wrapper that imports the adapter and calls
     `verl.trainer.main_ppo`.
   - `train_grpo_arena.sh`: shell launcher setting environment variables and
     Hydra overrides.
   - `docker-compose.yml`: reference stack with vLLM/SGLang backend.

### API / Usage Example

```bash
# 1. Start the OpenAgora server
./bin/openagora-server

# 2. Start vLLM (or SGLang) as the LLM backend
vllm serve Qwen/Qwen3.5-0.8B --enable-auto-tool-choice

# 3. Launch GRPO training
export ARENA_ENDPOINT=localhost:9090
export ARENA_AGENT_IMAGE=openagora-agent-minimal:latest
export ARENA_LLM_BACKEND=http://localhost:8000/v1

python examples/arena_grpo/train_grpo_arena.py \
  algorithm.adv_estimator=grpo \
  actor_rollout_ref.rollout.agent.default_agent_loop=arena_agent \
  ...
```

### Experiment Validation

- [ ] CPU smoke test: `train_cpu.py` converges for 10 steps on
  `Qwen/Qwen3.5-0.8B`.
- [ ] GPU GRPO test: `train_grpo_arena.sh` runs for one epoch on a single
  node with 4x A100.
- [ ] Unit tests: `pytest verl/agent_loop/tests/test_arena_agent_loop.py`.

### Checklist

- [ ] PR title follows `[{modules}] {type}: {description}`.
- [ ] Pre-commit hooks pass (`pre-commit run --all-files`).
- [ ] Added unit tests for new code.
- [ ] Updated documentation.
- [ ] Experiment validation completed and logs attached.
- [ ] Slack `ci-request` channel notified for CI rerun.

---

## File Mapping: OpenAgora Repo → Upstream veRL

| OpenAgora path | Proposed upstream path | Note |
|----------------|------------------------|------|
| `python/arena-verl/src/arena_verl/agent_loop.py` | `verl/agent_loop/arena_agent_loop.py` | Core integration |
| `python/arena-verl/src/arena_verl/rollout.py` | `verl/workers/rollout/arena_rollout.py` | Optional lower-level adapter |
| `python/arena-verl/src/arena_verl/rollout_provider.py` | `verl/workers/rollout/arena_rollout_provider.py` | Provider glue |
| `python/arena-sdk/src/arena_sdk/client.py` | `verl/utils/arena_client.py` or keep external | gRPC client |
| `examples/verl-integration/train_grpo_arena.py` | `examples/arena_grpo/train_grpo_arena.py` | Launcher wrapper |
| `examples/verl-integration/train_grpo_arena.sh` | `examples/arena_grpo/train_grpo_arena.sh` | Shell launcher |
| `examples/verl-integration/README.md` | `docs/advance/agent_loop.rst` (adapted) | Documentation |

> **Note on naming:** The upstream PR can use either the "Arena" abstraction
> name or the project name "OpenAgora". We recommend keeping "Arena" as the
> abstraction (e.g. `ArenaAgentLoop`) and "OpenAgora" as the project reference
> in docs, to avoid a disruptive rename inside the trainer code.

---

## Open Questions Before Submitting

1. Should the gRPC client live inside veRL, or should veRL depend on a
   published `openagora-sdk` package?
2. Which veRL commit/branch should we pin for the initial PR?
3. Do we want to upstream the `ArenaRollout` adapter, or only the AgentLoop
   path to keep the PR focused?
