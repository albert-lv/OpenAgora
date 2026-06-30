# Arena + veRL CPU Demo (Docker)

A fully self-contained, CPU-only end-to-end RL training demo that runs inside Docker.

## What it demonstrates

1. **Arena server** creates sandboxed agent rollouts.
2. **CPU trainer** loads a small LLM (Qwen/Qwen3.5-0.8B), collects rollouts, and computes rewards.
3. **Mock LLM** returns a deterministic correct solution (`add(a, b)`).
4. **Agent sandbox** writes `solution.py`, which passes verification.
5. **PPO update** runs on CPU and saves a checkpoint.

## Run it

```bash
cd examples/verl-integration
docker compose -f docker-compose.cpu-demo.yml up --build
```

The first run downloads the model (~1.6 GB) into `~/.cache/huggingface`. Subsequent runs use the cache.

## Expected output

```
cpu-trainer-1   | ============================================================
cpu-trainer-1   | Arena + veRL CPU PPO Demo Trainer
cpu-trainer-1   | ============================================================
cpu-trainer-1   | Model: Qwen/Qwen3.5-0.8B
cpu-trainer-1   | Device: cpu
cpu-trainer-1   | Arena endpoint: arena-server:9090
cpu-trainer-1   | LLM backend: http://mock-llm:8000/v1
cpu-trainer-1   | PPO iterations: 1, epochs/iteration: 2
...
cpu-trainer-1   |   sample 0: reward=1.0, response_tokens=17, logprobs=yes
cpu-trainer-1   |   sample 1: reward=1.0, response_tokens=17, logprobs=yes
...
cpu-trainer-1   |   Avg reward:     1.0000
...
cpu-trainer-1   |   epoch 1/2: loss=-0.1689, policy_loss=-0.1859, value_loss=0.0345, entropy=0.0358, approx_kl=0.000000
...
cpu-trainer-1   | ============================================================
cpu-trainer-1   | Training complete!
cpu-trainer-1   | ============================================================
```

Checkpoints are written to `examples/verl-integration/checkpoints/`.

## Configuration

Edit environment variables in `docker-compose.cpu-demo.yml`:

| Variable | Default | Description |
|----------|---------|-------------|
| `NUM_ITERATIONS` | 1 | Number of RL iterations |
| `PPO_EPOCHS` | 2 | PPO epochs per iteration |
| `BATCH_SIZE` | 2 | Rollouts per iteration |
| `MAX_PROMPT_LEN` | 32 | Prompt token budget |
| `MAX_RESPONSE_LEN` | 64 | Response token budget |
| `MODEL_NAME` | Qwen/Qwen3.5-0.8B | Hugging Face model name |

## Architecture

```
┌─────────────┐      gRPC      ┌─────────────────┐      Docker      ┌─────────────┐
│ cpu-trainer │◄──────────────►│  arena-server   │◄────────────────►│ agent sandbox│
└─────────────┘                └─────────────────┘                  └─────────────┘
                                      │                                    │
                                      │ HTTP /v1/chat/completions         │ OPENAI_BASE_URL
                                      ▼                                    ▼
                              ┌─────────────┐                      ┌─────────────┐
                              │   mock-llm  │                      │ arena proxy │
                              └─────────────┘                      └─────────────┘
```

## Notes

- The Arena server container needs the Docker socket and a host-mounted temp directory so it can create agent sandboxes that the host Docker daemon can bind-mount.
- Agent sandboxes are placed on the same Docker network (`arena-cpu-demo`) via the `ARENA_DOCKER_NETWORK` environment variable.
