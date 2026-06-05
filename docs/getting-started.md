# Getting Started

## Install

```bash
git clone https://github.com/albert-lv/agent-arena.git
cd agent-arena
```

## Build

### Go Server

```bash
make build
# → ./bin/arena-server
```

### Python SDK

```bash
cd python/arena-sdk
uv sync
```

### Docker Images

```bash
make docker-server    # arena-server:latest
make docker-agent     # arena-agent-minimal:latest
```

## Run

### 1. Start Arena Server

```bash
./bin/arena-server
# Listening on :9090
```

### 2. Start LLM Backend (or mock)

```bash
# Example: vLLM serving
python -m vllm.entrypoints.openai.api_server --model meta-llama/Llama-2-7b
```

### 3. Run Quickstart

```bash
cd examples/quickstart
./run.sh
```

## Next Steps

- Read [Sandbox Contract](sandbox-contract.md) to build your own agent
- Read [Architecture](architecture.md) to understand the four planes
- Check `examples/verl-integration/` for RL training integration
