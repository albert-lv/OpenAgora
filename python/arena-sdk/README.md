# Arena SDK

Python client and utilities for [Agent Arena](https://github.com/albert-lv/agent-arena).

The SDK provides a high-level interface for creating rollouts, streaming trajectories, and interacting with the Arena gRPC API from Python environments such as RL trainers, evaluation scripts, and agent orchestrators.

---

## Installation

```bash
# From the repository
cd python/arena-sdk
uv sync

# Or install in development mode
pip install -e .
```

Requires Python 3.10 or later.

---

## Quick Start

```python
from arena_sdk.client import ArenaClient

client = ArenaClient("localhost:9090")

rollout_id = client.create_rollout(
    task_id="my-task",
    image="arena-agent-minimal:latest",
    llm_backend="http://localhost:8000/v1",
)

result = client.wait(rollout_id)
print(f"Status: {result['status']}, Reward: {result['reward']}")

trajectory = client.get_trajectory(rollout_id)
print(f"Steps captured: {len(trajectory)}")
```

See [examples/quickstart](../../examples/quickstart/) for a runnable example.

---

## Features

- **Rollout management** — create, query, and wait for rollouts
- **Trajectory access** — fetch full trajectory data for RL training
- **Streaming support** — subscribe to rollout events in real time
- **Type-safe helpers** — Pydantic-based types for Arena resources

---

## Development

```bash
# Install dev dependencies
uv sync --extra dev

# Run tests
uv run pytest
```

---

## License

Apache-2.0 — see the [project license](../../LICENSE) for details.
