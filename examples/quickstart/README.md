# Quick Start Example

Run your first Arena rollout in about 5 minutes.

This example demonstrates the full Arena loop: creating a rollout, running an agent inside a Docker sandbox, capturing LLM calls through the proxy, and computing a reward.

---

## What You Will See

1. A rollout is created via the Arena gRPC API
2. Arena starts a Docker sandbox with a minimal Python agent
3. The agent reads its task, calls the LLM through Arena's proxy, and writes a `done` signal
4. Arena verifies the result and returns a reward
5. The full trajectory is printed

---

## Prerequisites

- [Docker](https://docs.docker.com/get-docker/) running locally
- [Go 1.25+](https://go.dev/dl/)
- [Python 3.10+](https://www.python.org/downloads/)
- [uv](https://docs.astral.sh/uv/getting-started/installation/) or `pip`

---

## Step 1: Build the Server

From the repository root:

```bash
make build
```

This produces `./bin/openagora-server`.

---

## Step 2: Start Arena

```bash
./bin/openagora-server
```

The server listens on `localhost:9090` by default. Leave this terminal open.

---

## Step 3: Build the Agent Image

```bash
make docker-agent
```

This builds `openagora-agent-minimal:latest`, a tiny Python agent that follows the [Sandbox Contract](../../docs/sandbox-contract.md).

---

## Step 4: Run the Rollout

In another terminal, from the repository root:

```bash
cd examples/quickstart
./run.sh
```

The script will install the `openagora-sdk` Python package if needed, then submit the rollout and wait for completion.

---

## Expected Output

```
Creating rollout via Arena (localhost:9090)...
Rollout created: <rollout-uuid>
Waiting for completion...
Status: success
Reward: 1.0
Trajectory steps: 4
  step 0: prompt=12 completion=5
  step 1: prompt=18 completion=7
  ...
```

If you see `success` and a non-empty trajectory, everything is wired up correctly.

---

## Customize the Rollout

Edit `task.json` to change the task description, sampling parameters, or verification command.

```json
{
  "task_id": "demo-task",
  "description": "Say hello to Arena",
  "sandbox_image": "openagora-agent-minimal:latest",
  "llm_backend": "http://localhost:8000/v1",
  "sampling": {
    "temperature": 0.7,
    "max_tokens": 128
  },
  "verify": {
    "command": "python -m pytest /sandbox/tests"
  }
}
```

> **Note:** `llm_backend` should point to an OpenAI-compatible endpoint. The example uses a local vLLM server on port `8000`. If you do not have a real backend, the minimal agent will still demonstrate the contract.

---

## Explore the Code

- `run.sh` — one-liner that sets up the SDK and invokes the Python script
- `run_rollout.py` — uses `openagora_sdk.client.ArenaClient` to create and monitor a rollout
- `task.json` — task definition consumed by the agent and Arena

Use these files as a template for your own rollouts.

---

## Troubleshooting

### `openagora-sdk` import error

Make sure `uv` or `pip` can install the package. The quickstart tries `pip install -e` automatically.

### Docker permission error

Ensure your user can run Docker commands. On Linux, you may need to add your user to the `docker` group and log out/back in.

### Connection refused on `:9090`

The Arena server is not running. Go back to Step 2 and start it.

### Connection refused on `:8000` (LLM backend)

`task.json` points to an OpenAI-compatible endpoint at `http://localhost:8000/v1`.
You can start a local backend with Ollama:

```bash
ollama pull qwen3.5:0.8b
ollama serve
```

Then change `llm_backend` in `task.json` to `http://localhost:11434/v1`.
Alternatively, start vLLM:

```bash
vllm serve Qwen/Qwen3.5-0.8B
```

---

## Next Steps

- Read the [Sandbox Contract](../../docs/sandbox-contract.md) to package your own agent
- Read the [Architecture](../../docs/architecture.md) doc to understand how data flows
- Explore [examples/verl-integration/](../verl-integration/) to connect Arena to an RL trainer
