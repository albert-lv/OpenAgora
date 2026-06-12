# Getting Started with Agent Arena

Welcome! This guide will walk you through building Arena from source, running your first rollout, and connecting your own agent.

> **New to Arena?** Start with the [README](../README.md) for a project overview and the [Architecture doc](architecture.md) to understand how the pieces fit together.

---

## Table of Contents

- [Prerequisites](#prerequisites)
- [Clone and Build](#clone-and-build)
- [Start the Server](#start-the-server)
- [Run the Quickstart](#run-the-quickstart)
- [Build the Python SDK](#build-the-python-sdk)
- [Build Docker Images](#build-docker-images)
- [Run Tests](#run-tests)
- [Next Steps](#next-steps)
- [Troubleshooting](#troubleshooting)

---

## Prerequisites

Make sure the following tools are installed on your machine:

| Tool | Recommended Version | Purpose |
|------|---------------------|---------|
| [Go](https://go.dev/dl/) | 1.25+ | Core server and proxy |
| [Python](https://www.python.org/downloads/) | 3.10+ | SDK, verification, trainer adapters |
| [uv](https://docs.astral.sh/uv/getting-started/installation/) | latest | Python dependency management |
| [Docker](https://docs.docker.com/get-docker/) | latest | Sandbox runtime |
| [Make](https://www.gnu.org/software/make/) | any | Build automation |
| [protoc](https://grpc.io/docs/protoc-installation/) | 3.x+ | Only needed if modifying `.proto` files |

Verify your setup:

```bash
go version
python3 --version
uv --version
docker --version
```

---

## Clone and Build

```bash
git clone https://github.com/albert-lv/agent-arena.git
cd agent-arena
make build
```

This compiles the Go server and places the binary at `./bin/arena-server`.

---

## Start the Server

```bash
./bin/arena-server
```

By default the server listens on `:9090`. You should see log output indicating that the gRPC server and sandbox provider are ready.

> **Note:** The quickstart uses the Docker sandbox provider by default. Make sure Docker is running before proceeding. If you do not have Docker, you can start the server with a mock sandbox instead:
> ```bash
> ./bin/arena-server --sandbox=mock
> ```
> The mock provider does not create real containers, but the rest of the flow (proxy, trajectory, verification) works normally.

> **Note on LLM backend:** The default `task.json` in `examples/quickstart` points to a mock LLM server at `http://localhost:8000/v1`. For real inference you can use any OpenAI-compatible endpoint. Arena currently supports three backend options:
>
> 1. **Ollama** — easiest for local CPU/GPU development (`http://localhost:11434/v1`).
> 2. **vLLM** — recommended for high-throughput GPU inference (`http://localhost:8000/v1`).
> 3. **SGLang** — drop-in vLLM alternative, also served on port `8000` by convention in our examples.
>
> The proxy automatically detects ollama and only injects `logprobs`, while vLLM/SGLang get `logprobs` plus `top_logprobs` for richer RL training signals.

---

## Run the Quickstart

In a second terminal:

```bash
cd examples/quickstart
./run.sh
```

This script will:

1. Ensure the `arena-sdk` Python package is installed
2. Create a rollout via the Arena gRPC API
3. Start a Docker sandbox running the minimal agent
4. Capture LLM calls through the Arena proxy
5. Run verification and print the reward

If everything works, you will see output like:

```
Rollout created: <uuid>
Waiting for completion...
Status: success
Reward: 1.0
Trajectory steps: 4
```

For a deeper walkthrough, see [examples/quickstart/README.md](../examples/quickstart/README.md).

---

## Switch the Inference Backend

The inference backend is selected per-rollout via the `llm_backend` field passed to `CreateRollout`. No server restart is required.

### Ollama (default local backend)

```bash
ollama run qwen3.5:0.8b
# llm_backend: http://localhost:11434/v1
```

### vLLM

Build and start the optional vLLM image:

```bash
docker build -f docker/Dockerfile.vllm -t arena-vllm:latest .
docker run --rm --gpus all -p 8000:8000 \
  -v ~/.cache/huggingface:/root/.cache/huggingface \
  arena-vllm:latest \
  --model Qwen/Qwen3.5-0.8B --served-model-name qwen3.5:0.8b
```

Then point rollouts to `http://localhost:8000/v1`.

For a fully orchestrated stack, use the vLLM compose file:

```bash
export VLLM_MODEL=Qwen/Qwen3.5-0.8B
docker compose -f examples/verl-integration/docker-compose.vllm.yml up --build
```

### SGLang

SGLang exposes an OpenAI-compatible server as well. Replace the vLLM image with `lmsysorg/sglang:latest` in the compose file, expose port `30000`, and set `ARENA_LLM_BACKEND=http://sglang:30000/v1`.

---

## Build the Python SDK

The Python SDK is used by quickstart scripts, verification runners, and trainer adapters.

```bash
cd python/arena-sdk
uv sync --extra dev
```

To install it in editable mode for local development:

```bash
pip install -e .
```

Repeat the same steps for `python/arena-verify` and `python/arena-verl` if you plan to work on those components.

---

## Build Docker Images

Arena uses Docker as its default sandbox provider. Build the included images:

```bash
# Server image (optional for local dev, useful for deployment)
make docker-server

# Minimal agent image (used by the quickstart)
make docker-agent
```

You can also build your own agent image as long as it follows the [Sandbox Contract](sandbox-contract.md).

---

## Run Tests

We recommend running the full test suite before opening a pull request:

```bash
# Run all tests (Go + Python)
make test

# Run only Go tests
cd go && go test ./...

# Run only Python tests
make sdk-test
```

Individual Python packages can be tested with:

```bash
cd python/arena-sdk && uv run pytest
cd python/arena-verify && uv run pytest
cd python/arena-verl && uv run pytest
```

---

## Next Steps

Now that you have Arena running, here are some natural next steps:

- **Read the [Sandbox Contract](sandbox-contract.md)** to learn how to package your own agent.
- **Read [Architecture](architecture.md)** to understand the four planes and how data flows through the system.
- **Explore [examples/verl-integration/](../examples/verl-integration/)** to see how Arena connects to RL training loops.
- **Check the [Contributing Guide](../CONTRIBUTING.md)** if you want to improve Arena.

---

## Troubleshooting

### `make build` fails with a Go version error

Arena requires Go 1.25 or later. Install a newer version from [go.dev/dl](https://go.dev/dl/).

### Docker is not available

The quickstart requires Docker. If you cannot run Docker locally, you can still develop against the Go server and Python SDK, but sandbox execution will not work until a remote provider is configured.

### `uv sync` fails

Make sure you have [uv](https://docs.astral.sh/uv/getting-started/installation/) installed and that you are inside the correct Python package directory (`python/arena-sdk`, `python/arena-verify`, or `python/arena-verl`).

### Port 9090 is already in use

Either stop the other service on port 9090, or run the server with a different port if your deployment supports it.

---

Need more help? Open a [GitHub Discussion](https://github.com/albert-lv/agent-arena/discussions) or [issue](https://github.com/albert-lv/agent-arena/issues).
