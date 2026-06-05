# Agent Arena

**Arena is an open-source rollout, verification, and trajectory plane for agentic RL.**

It provides the missing infrastructure layer between RL trainers (veRL, ROLL, TRL) and agent execution environments:

- **Rollout Control Plane** — LLM proxy with transparent trajectory capture and sampling injection
- **Sandbox Plane** — Containerized agent execution (Docker v1, extensible to E2B/ROCK)
- **Verification Plane** — Decoupled reward computation (pytest, custom evaluators)
- **Trajectory Data Plane** — Structured, append-only trajectory storage for RL training

---

## Quick Start

```bash
# Build
git clone https://github.com/albert-lv/agent-arena.git
cd agent-arena
make build

# Start arena server + vLLM mock
make dev

# Run a rollout
./examples/quickstart/run.sh
```

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│ RL Trainer (veRL / ROLL / TRL)                              │
│ 消费 trajectory + reward，执行 PPO/GRPO/StarPO 训练           │
└────────────────────────────┬────────────────────────────────┘
                             │ gRPC streaming
┌────────────────────────────▼────────────────────────────────┐
│ Arena (Go core + Python SDK)                                  │
│                                                               │
│  ┌─────────────────┐  ┌──────────────┐  ┌─────────────────┐  │
│  │ Rollout Control │  │ Verification │  │ Trajectory Data │  │
│  │ Plane (LLM Proxy)│  │ Plane        │  │ Plane           │  │
│  └────────┬────────┘  └──────────────┘  └─────────────────┘  │
│           │                                                   │
│  ┌────────▼────────┐                                         │
│  │ Sandbox Plane     │                                         │
│  │ (Docker v1)       │                                         │
│  └─────────────────┘                                           │
└──────────────────────────────────────────────────────────────┘
                           │
              Agent in Container (OpenHands / SWE-agent / custom)
```

See [docs/architecture.md](docs/architecture.md) for details.

---

## Why Arena?

| Capability | Arena | ROCK | LiteLLM | E2B | SWE-Gym |
|-----------|-------|------|---------|-----|---------|
| LLM Proxy (active control) | ✅ | ❌ | passive | ❌ | ❌ |
| Sampling injection | ✅ | ❌ | ❌ | ❌ | ❌ |
| Independent Verification | ✅ | ❌ | ❌ | ❌ | coupled |
| RL-grade Trajectory Schema | ✅ | ❌ | ❌ | ❌ | ❌ |

---

## License

Apache-2.0
