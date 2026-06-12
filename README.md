# OpenAgora

[![Go CI](https://github.com/albert-lv/OpenAgora/actions/workflows/go.yml/badge.svg)](https://github.com/albert-lv/OpenAgora/actions/workflows/go.yml)
[![Python CI](https://github.com/albert-lv/OpenAgora/actions/workflows/python.yml/badge.svg)](https://github.com/albert-lv/OpenAgora/actions/workflows/python.yml)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![Go Version](https://img.shields.io/badge/Go-1.25+-00ADD8?logo=go)](https://go.dev/)
[![Python Version](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python)](https://www.python.org/)

**Arena is an open-source rollout, verification, and trajectory plane for agentic reinforcement learning.**

It provides the missing infrastructure layer between RL trainers (veRL, ROLL, TRL) and agent execution environments. Whether you are building a coding agent, a web agent, or a general-purpose autonomous system, Arena gives you a reproducible, observable, and RL-ready execution pipeline.

---

## What is Arena?

Training agents with reinforcement learning requires more than just an LLM API. You need:

- **Controlled rollouts** — deterministic sampling, token budgets, and trajectory capture
- **Sandboxed execution** — safe, reproducible environments for your agents
- **Decoupled verification** — reward computation independent from agent logic
- **Structured trajectory data** — training-grade data for PPO, GRPO, DPO, and more

Arena provides all four as composable, language-agnostic planes.

### Four Planes

| Plane | Purpose | Status |
|-------|---------|--------|
| **Rollout Control Plane** | LLM proxy with sampling injection and trajectory capture | ✅ Available |
| **Sandbox Plane** | Containerized agent execution (Docker v1) | ✅ Available |
| **Verification Plane** | Decoupled reward computation (pytest, custom evaluators) | ✅ Available |
| **Trajectory Data Plane** | Structured, append-only trajectory storage | ✅ Available |

See [docs/architecture.md](docs/architecture.md) for the full design.

---

## Quick Start

Get your first rollout running in under 5 minutes.

### Prerequisites

- [Docker](https://docs.docker.com/get-docker/)
- [Go 1.25+](https://go.dev/dl/)
- [Python 3.10+](https://www.python.org/downloads/)
- [uv](https://docs.astral.sh/uv/getting-started/installation/) (for Python development)

### 1. Clone and Build

```bash
git clone https://github.com/albert-lv/OpenAgora.git
cd OpenAgora
make build
```

### 2. Start the Arena Server

```bash
./bin/openagora-server
# Server listening on :9090
```

> **Note:** The quickstart uses the Docker sandbox provider by default. Make sure Docker is installed and running before proceeding. If you do not have Docker, you can start the server with a mock sandbox instead:
> ```bash
> ./bin/openagora-server --sandbox=mock
> ```
> The mock provider does not create real containers, but the rest of the flow (proxy, trajectory, verification) works normally.

> **Note on LLM backend:** The default `task.json` points to a mock LLM. Arena supports Ollama, vLLM, and SGLang as inference backends. The proxy injects `logprobs` for all backends and `top_logprobs` for vLLM/SGLang. See [docs/getting-started.md](docs/getting-started.md) for backend setup instructions.

### 3. Run Your First Rollout

In another terminal:

```bash
cd examples/quickstart
./run.sh
```

You should see a rollout complete with captured trajectory steps and a reward.

For more details, check out [examples/quickstart/README.md](examples/quickstart/README.md) and [docs/getting-started.md](docs/getting-started.md).

---

## Why Arena?

| Capability | Arena | ROCK | LiteLLM | E2B | SWE-Gym |
|-----------|-------|------|---------|-----|---------|
| LLM Proxy with active control | ✅ | ❌ | passive | ❌ | ❌ |
| Sampling injection per rollout | ✅ | ❌ | ❌ | ❌ | ❌ |
| Independent verification plane | ✅ | ❌ | ❌ | ❌ | coupled |
| RL-grade trajectory schema | ✅ | ❌ | ❌ | ❌ | ❌ |
| Language-agnostic agent contract | ✅ | partial | N/A | partial | partial |

---

## Project Structure

```
OpenAgora/
├── go/                      # Go core (server, proxy, sandbox orchestration)
│   ├── cmd/                 # Binaries (openagora-server, demo)
│   └── pkg/                 # Reusable packages
├── proto/                   # Protobuf / gRPC schemas
├── python/                  # Python ecosystem
│   ├── openagora-sdk/           # Python client for Arena
│   ├── openagora-verify/        # Verification plugins
│   └── openagora-verl/          # veRL trainer adapter
├── docker/                  # Docker images
├── docs/                    # Documentation
├── examples/                # Quickstart and trainer integrations
├── Makefile                 # Common development tasks
└── README.md                # You are here
```

---

## Installation

### Go Server

```bash
make build
# Output: ./bin/openagora-server
```

### Python SDK

```bash
cd python/openagora-sdk
uv sync
```

### Docker Images

```bash
make docker-server    # openagora-server:latest
make docker-agent     # openagora-agent-minimal:latest
```

---

## Usage Examples

### Build a Custom Agent

Any container that follows the [Sandbox Contract](docs/sandbox-contract.md) can run in Arena. The contract is simple:

1. Read the task from `/sandbox/.arena/task.json`
2. Route LLM calls through the `OPENAI_BASE_URL` injected by Arena
3. Signal completion by writing `/sandbox/.arena/done`

That is it — language-agnostic and framework-agnostic.

### Python Client

```python
from openagora_sdk.client import ArenaClient

client = ArenaClient("localhost:9090")

rollout_id = client.create_rollout(
    task_id="my-task",
    image="openagora-agent-minimal:latest",
    llm_backend="http://localhost:8000/v1",
)

result = client.wait(rollout_id)
print(f"Status: {result['status']}, Reward: {result['reward']}")
```

More examples live in [examples/](examples/).

---

## Roadmap

We are building Arena in public. Here is what is coming next:

- [ ] Additional sandbox providers (E2B, OpenSandbox)
- [ ] Parquet and S3 trajectory backends
- [ ] Streaming trajectory consumption for online RL
- [ ] More verification plugins (SWE-bench style, LLM-as-judge)
- [ ] Distributed rollout workers
- [ ] Observability dashboards

Have an idea? Open a [discussion](https://github.com/albert-lv/OpenAgora/discussions) or [issue](https://github.com/albert-lv/OpenAgora/issues).

---

## Contributing

We love contributions! Please read our [Contributing Guide](CONTRIBUTING.md) to get started.

A few quick ways to help:

- **Report bugs** — [open an issue](https://github.com/albert-lv/OpenAgora/issues/new?template=bug_report.md)
- **Request features** — [open an issue](https://github.com/albert-lv/OpenAgora/issues/new?template=feature_request.md)
- **Submit improvements** — [open a pull request](https://github.com/albert-lv/OpenAgora/pulls)
- **Spread the word** — star the repo and share with others

Please note that this project is released with a [Contributor Code of Conduct](CODE_OF_CONDUCT.md). By participating, you agree to abide by its terms.

---

## Community

- 💬 [GitHub Discussions](https://github.com/albert-lv/OpenAgora/discussions) — ask questions, share ideas
- 🐛 [GitHub Issues](https://github.com/albert-lv/OpenAgora/issues) — bug reports and feature requests
- 📧 For security issues, please email the maintainers directly instead of opening a public issue

---

## License

OpenAgora is licensed under the [Apache License 2.0](LICENSE).

---

<p align="center">Built with ❤️ for the open agentic RL community.</p>
