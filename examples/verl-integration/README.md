# Arena + veRL End-to-End Integration

This example demonstrates how to use **OpenAgora** as the agent execution and
verification backend for **veRL** training.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         veRL Trainer                             │
│  ┌─────────────┐    ┌─────────────────┐    ┌─────────────────┐  │
│  │ FSDP Actor  │◄──►│  ArenaAgentLoop │◄──►│  Arena Server   │  │
│  │  (GPU)      │    │  (Agent Loop)   │    │  (gRPC :9090)   │  │
│  └─────────────┘    └─────────────────┘    └─────────────────┘  │
│         ▲                                           │            │
│         │                                           │ Docker     │
│         │                                           ▼            │
│  ┌─────────────┐                         ┌─────────────────┐    │
│  │ vLLM Server │◄────────────────────────│  Agent Sandbox  │    │
│  │  (GPU)      │   HTTP /v1/chat/completions               │    │
│  └─────────────┘                         └─────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
```

Key points:

- **veRL's vLLM/SGLang server** stays in charge of LLM inference and weight
  updates. Nothing changes on the inference side.
- **ArenaAgentLoop** replaces veRL's built-in `single_turn_agent` or
  `tool_agent`. It submits each training sample to Arena as a sandboxed
  rollout.
- **Arena Proxy** transparently forwards the agent's LLM calls to the veRL
  inference server.
- **Arena Verification** computes the reward (e.g. `pytest`) and returns it to
  veRL via `AgentLoopOutput.reward_score`.

## Prerequisites

1. **Arena Server** running (see project root `README.md`).
2. **veRL** installed with your target backend (vLLM or SGLang).
3. An **agent Docker image** that follows the
   [Arena Sandbox Contract](../../docs/sandbox-contract.md).

## Quick Start

### 1. Start Arena Server

```bash
cd /path/to/OpenAgora
make build
./bin/openagora-server
# Server listening on :9090
```

### 2. Build or Pull an Agent Image

```bash
# Using the minimal example agent from the repo
make docker-agent
# Produces: openagora-agent-minimal:latest
```

Or build your own (e.g. OpenHands, SWE-agent) as long as it reads
`/sandbox/.arena/task.json` and routes LLM calls through `OPENAI_BASE_URL`.

### 3. Launch veRL with Arena Agent Loop

#### Option A: Environment Variables (Quickest)

```bash
export ARENA_ENDPOINT="localhost:9090"
export ARENA_AGENT_IMAGE="openagora-agent-minimal:latest"
export ARENA_LLM_BACKEND="http://localhost:8000/v1"   # your vLLM/SGLang server
export ARENA_VERIFY_COMMAND="pytest -k regression"

python -m verl.trainer.main_ppo \
  actor_rollout_ref.rollout.agent.default_agent_loop="arena_agent" \
  ...  # rest of your normal veRL args
```

> **Note:** You must `import openagora_verl` in your training script (or in
> `verl/experimental/agent_loop/__init__.py`) so that the `@register("arena_agent")`
> decorator executes before veRL instantiates the agent loop.

#### Option B: Hydra Config File (Recommended for Reproducibility)

Create `arena_agent_loop.yaml`:

```yaml
# arena_agent_loop.yaml
name: arena_agent
_target_: openagora_verl.agent_loop.ArenaAgentLoop
trainer_config:
  config: ${config}
server_manager: ${server_manager}
tokenizer: ${tokenizer}
processor: ${processor}
dataset_cls: ${dataset_cls}
data_config: ${data_config}
```

Then reference it in your veRL launch command:

```bash
python -m verl.trainer.main_ppo \
  actor_rollout_ref.rollout.agent.agent_loop_config_path=arena_agent_loop.yaml \
  actor_rollout_ref.rollout.agent.default_agent_loop=arena_agent \
  ...
```

### 4. Minimal Launch Script

`train_grpo_arena.sh`:

```bash
#!/bin/bash
set -e

# Arena settings
export ARENA_ENDPOINT="localhost:9090"
export ARENA_AGENT_IMAGE="openagora-agent-minimal:latest"
export ARENA_LLM_BACKEND="http://localhost:8000/v1"
export ARENA_VERIFY_COMMAND="pytest -k regression"
export ARENA_TIMEOUT_SECONDS="600"

# Ensure openagora_verl is imported so the agent loop registers
export PYTHONPATH="/path/to/OpenAgora/python/openagora-verl/src:${PYTHONPATH}"

python -m verl.trainer.main_ppo \
  algorithm.adv_estimator=grpo \
  data.train_files=... \
  data.val_files=... \
  data.train_batch_size=32 \
  data.max_prompt_length=512 \
  data.max_response_length=1024 \
  actor_rollout_ref.model.path=Qwen/Qwen2.5-7B-Instruct \
  actor_rollout_ref.rollout.name=vllm \
  actor_rollout_ref.rollout.agent.default_agent_loop=arena_agent \
  trainer.n_gpus_per_node=4 \
  trainer.nnodes=1
```

## How It Works

1. **Data loading** — veRL loads your dataset (e.g. SWE-bench, GSM8K with tools).
2. **Rollout** — For each batch sample, `ArenaAgentLoop.run()`:
   - Encodes the prompt messages into a task JSON.
   - Calls `ArenaClient.create_rollout()` to start a Docker sandbox.
   - The sandboxed agent reads the task and starts making LLM calls.
   - LLM calls hit `Arena Proxy`, which forwards them to your vLLM/SGLang
     server.
   - Arena captures every request/response into the trajectory data plane.
   - When the agent writes `/sandbox/.arena/done`, Arena runs verification
     (e.g. `pytest`) and computes a reward.
3. **Return to trainer** — `ArenaAgentLoop` fetches the trajectory,
   tokenizes the prompt + response, and returns an `AgentLoopOutput`.
   veRL's post-processing pads tensors and assembles the `DataProto` batch.
4. **Training** — veRL computes advantages and updates the actor model as
   usual. The updated weights are pushed to the vLLM/SGLang server for the
   next rollout round.

## Customization

### Per-Sample Agent Images or Verify Commands

If different samples need different sandbox images, you can subclass
`ArenaAgentLoop` and override `run()` to read `kwargs["extra_info"]`:

```python
class CustomArenaAgentLoop(ArenaAgentLoop):
    async def run(self, sampling_params, **kwargs):
        extra = kwargs.get("extra_info", {})
        self._agent_image = extra.get("arena_image", self._agent_image)
        self._verify_command = extra.get("openagora_verify", self._verify_command)
        return await super().run(sampling_params, **kwargs)
```

### Multi-Turn Agents

The default `ArenaAgentLoop` treats the entire sandbox execution as a single
response (`response_mask = [1, 1, ..., 1]`). If your agent performs explicit
tool calls that you want to mask as observations (`response_mask = 0`), you
should implement a custom agent loop that parses Arena's trajectory step by
step.

## Troubleshooting

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| `Agent loop arena_agent not registered` | `openagora_verl` not imported before veRL instantiates the loop | Add `import openagora_verl` at the top of your training script |
| `sandbox create: ...` | Docker not available or image not pulled | Check `docker ps` and `docker pull $ARENA_AGENT_IMAGE` |
| `token budget exhausted` | Agent is making too many LLM calls | Increase `max_tokens_budget` in sampling config or reduce agent turns |
| Reward always `0.0` | Verify command failing silently | Check Arena server logs; run verify command manually inside the sandbox |

## See Also

- [Arena Sandbox Contract](../../docs/sandbox-contract.md)
- [Arena Architecture](../../docs/architecture.md)
- [veRL Agent Loop Docs](https://github.com/volcengine/verl/tree/main/docs) (upstream)
