# Arena veRL Adapter

Integration layer that connects [veRL](https://github.com/volcengine/verl) to [Agent Arena](https://github.com/albert-lv/agent-arena).

Instead of replacing veRL's inference engine (vLLM/SGLang), this adapter
registers Arena as a **veRL Agent Loop**. The agent runs inside Arena's
sandboxed environment while LLM calls are transparently proxied back to veRL's
inference server.

---

## Installation

```bash
cd python/arena-verl
uv sync --extra dev
```

For development with veRL installed (Linux with CUDA recommended):

```bash
uv sync --extra verl --extra dev
```

Requires Python 3.10 or later. The core adapter installs without veRL and falls
back to standalone mocks when veRL is not present.

---

## Quick Start

### 1. Import `arena_verl` in your training script

This triggers the `@register("arena_agent")` decorator so veRL can find the
agent loop.

```python
import arena_verl  # noqa: F401
```

### 2. Set environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `ARENA_ENDPOINT` | `localhost:9090` | Arena gRPC server address |
| `ARENA_AGENT_IMAGE` | `arena-agent-minimal:latest` | Docker image for sandboxed agent |
| `ARENA_LLM_BACKEND` | `http://localhost:8000/v1` | OpenAI-compatible LLM endpoint (veRL's vLLM/SGLang server) |
| `ARENA_VERIFY_COMMAND` | `true` | Command to run for verification/reward |
| `ARENA_TIMEOUT_SECONDS` | `3600` | Max seconds to wait for a rollout |

### 3. Launch veRL with the Arena agent loop

```bash
python -m verl.trainer.main_ppo \
  actor_rollout_ref.rollout.agent.default_agent_loop=arena_agent \
  ... # other veRL args
```

See [examples/verl-integration](../../examples/verl-integration/) for a
complete GRPO training script.

---

## Architecture

```
veRL Trainer
    └── AgentLoopWorker.generate_sequences()
            └── ArenaAgentLoop.run()
                    ├── ArenaClient.create_rollout()   →  Arena Server
                    │                                         └── Docker Sandbox
                    │                                               └── Agent
                    │                                                     └── LLM call
                    │                                                           └── Arena Proxy
                    │                                                                 └── vLLM/SGLang
                    ├── ArenaClient.wait()             ←  reward + status
                    └── tokenize trajectory            →  AgentLoopOutput
```

---

## Components

### `ArenaAgentLoop`

A veRL `AgentLoopBase` implementation that delegates execution to Arena.

Key behaviour:

- **Prompt encoding** — Uses the model's tokenizer / processor to render
  `raw_prompt` messages into text and then into token IDs.
- **Rollout creation** — Submits the task to Arena with the configured sandbox
  image, LLM backend, and sampling parameters.
- **Trajectory extraction** — Fetches the captured HTTP request/response pairs
  from Arena's data plane and reconstructs the agent's response text.
- **Logprobs** — If the LLM backend returns per-token logprobs (requested
  automatically by Arena Proxy), they are extracted and returned as
  `response_logprobs`.
- **Reward** — Reads the reward computed by Arena's verification plane.

### `ArenaRolloutProvider` (legacy)

A standalone batch rollout provider for cases where you don't need the full
veRL trainer integration. Use `ArenaAgentLoop` for new projects.

---

## Development

```bash
uv sync --extra dev
uv run pytest
```

---

## License

Apache-2.0 — see the [project license](../../LICENSE) for details.
