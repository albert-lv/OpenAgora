# Quick Start

Run your first Arena rollout in 5 minutes.

## Prerequisites

- Docker
- Go 1.23+
- Python 3.10+

## Start Arena Server

```bash
make build
./bin/arena-server
```

## Run a Rollout

```bash
./run.sh
```

This will:
1. Create a rollout via Arena gRPC
2. Start a Docker sandbox with the minimal agent
3. Capture LLM calls through the proxy
4. Run verification and output reward
