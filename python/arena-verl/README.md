# Arena veRL Adapter

Trainer adapter that connects [veRL](https://github.com/volcengine/verl) to [Agent Arena](https://github.com/albert-lv/agent-arena).

This package implements the rollout provider interface expected by veRL, allowing you to use Arena as the execution and trajectory collection backend for your RL training jobs.

---

## Installation

```bash
cd python/arena-verl
uv sync
```

Requires Python 3.10 or later. Make sure `arena-sdk` is available — it is declared as a local path dependency.

---

## Quick Start

```python
from arena_verl.rollout_provider import ArenaRolloutProvider

provider = ArenaRolloutProvider(
    endpoint="localhost:9090",
    agent_image="arena-agent-minimal:latest",
    llm_backend="http://localhost:8000/v1",
)

trajectories = provider.rollout(tasks)
```

See [examples/verl-integration](../../examples/verl-integration/) for a complete training example.

---

## Features

- **Native veRL integration** — implements the rollout provider contract
- **Batched rollouts** — run multiple tasks through Arena in parallel
- **Reward + trajectory return** — data ready for PPO/GRPO training loops

---

## Development

```bash
uv sync --extra dev
uv run pytest
```

---

## License

Apache-2.0 — see the [project license](../../LICENSE) for details.
