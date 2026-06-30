# Relationship Chat Assistant — RL Training on CPU + Ollama Deployment

An end-to-end example: train `Qwen/Qwen3.5-0.8B` with PPO purely on CPU so it learns "how to chat with your girlfriend/wife without stepping on landmines," then watch the verify success rate rise on the Arena Dashboard, and finally deploy the RL-tuned model via Ollama as a chat application.

> This example defaults to `Qwen/Qwen3.5-0.8B` as the actor model and `qwen3.5:0.8b` as the Ollama rollout backend. Before running, make sure the model is downloaded to the local HuggingFace cache (`~/.cache/huggingface`) and available in Ollama.

## Scenario

We turn "chatting with your partner" into a reinforcement-learning task:

- **Input**: She sends a message that is easy to mishandle (e.g., "You forgot our anniversary again").
- **Action**: The model generates a reply in English.
- **Reward**: Given by a hidden rubric; avoiding minefields like "what's the big deal" / "calm down" and including empathetic phrases like "I understand" / "I'm sorry" / "I'm here for you" yields a high score.
- **Goal**: Through Arena + PPO, the model learns to comfort her better, and the verify success rate keeps climbing on the Dashboard.

## Project Structure

```
examples/relationship-chat-rl/
├── data/
│   ├── build_dataset.py          # generates scenarios.jsonl
│   └── scenarios.jsonl           # 12 chat scenarios + hidden rubric
├── agent/
│   ├── Dockerfile                # custom sandbox agent
│   └── chat_agent.py             # calls LLM and saves the reply
├── verify/
│   └── score_response.py         # computes a 0~1 reward from the rubric
├── train_relationship_chat.py    # CPU PPO training script
├── docker-compose.yml            # one-command CPU training stack
├── deploy_to_ollama.py           # imports the LoRA checkpoint into Ollama
├── chat.py                       # chat with the model via the OpenAI API
└── README.md                     # this file
```

## Prerequisites

- Docker + Docker Compose
- At least 8 GB RAM (16 GB recommended)
- `Qwen/Qwen3.5-0.8B` pre-downloaded to `~/.cache/huggingface`
- `qwen3.5:0.8b` pre-downloaded to local Ollama (or allowed to pull inside the container)

## Quick Start

```bash
cd examples/relationship-chat-rl

# 1. Start the training stack (first image build takes a few minutes)
docker compose up --build

# 2. Open the Arena Dashboard
open http://localhost:9091
# Click the "Verify Stats" tab to see the real-time Verify Success Rate line chart rise gradually.
```

During training you will see:

- Each rollout's reward (0~1) is recorded by the Arena server.
- The Dashboard's **Verify Stats → Verify Success Rate Trend** line chart rises as more samples are collected.
- After each iteration, the LoRA checkpoint is saved to `./checkpoints/checkpoint-N/`.

## How It Works

```
scenarios.jsonl
      │
      ▼
+-------------+      +----------------+      +------------------+
| CPU Trainer |─────▶| Arena Server   |─────▶| relationship-    |
| (PPO/LoRA)  |      | (sandbox/proxy)|      | chat-agent       |
+-------------+      +----------------+      +------------------+
      ▲                     │                           │
      │                     │                           ▼
      │              trajectory + reward         Ollama (qwen3.5:0.8b)
      │                     │                           │
      │                     ▼                           │
      │            score_response.py                    │
      │            (rubric 0~1 reward)                  │
      │                                                   │
      └───────────────────────────────────────────────────┘
```

1. **Rollout**: The trainer creates an Arena rollout for each scenario; the agent calls Ollama inside the sandbox to generate a reply and writes it to `/sandbox/response.txt`.
2. **Verify**: Arena runs `python /app/score_response.py`, reads the rubric in `task.json`, and outputs a continuous 0~1 reward to `/sandbox/.arena/rewards.jsonl`.
3. **PPO Update**: The trainer uses the returned rewards to compute advantages and updates the LoRA adapter on CPU.
4. **Loop**: The next round of rollouts uses the updated policy, and reply quality gradually improves.

## Dashboard Screenshots

After training, the Arena Dashboard displays rollout, verify, and token statistics:

| Rollouts | Verify Stats | Token Stats |
|---|---|---|
| ![Relationship Chat Rollouts](../../screenshots/relationship-chat-rollouts.png) | ![Relationship Chat Verify Stats](../../screenshots/relationship-chat-verify-stats.png) | ![Relationship Chat Token Stats](../../screenshots/relationship-chat-token-stats.png) |

## View Training Metrics

The training script writes per-iteration metrics to `./data/metrics.jsonl`:

```bash
# View live metrics in another terminal
tail -f examples/relationship-chat-rl/data/metrics.jsonl
```

Field descriptions:

- `step`: PPO iteration
- `avg_reward`: average reward this iteration
- `verify_success_rate`: proportion of samples with reward > 0
- `min_reward` / `max_reward`: min/max reward this iteration

Also open the Dashboard's **Verify Stats** tab to see:

- Current **Success Rate** card
- **Reward Distribution** histogram
- **Verify Success Rate Trend** cumulative success-rate line chart (new in this example)

## Deploy to Ollama

After training, the latest LoRA adapter is in `./checkpoints/checkpoint-1/` (the iteration count can be adjusted via `NUM_ITERATIONS`). Because the base model is `qwen3.5:0.8b`, Ollama can import the Safetensors-format LoRA adapter directly:

```bash
cd examples/relationship-chat-rl

# Option 1: Use the script to create the Ollama model automatically
python3 deploy_to_ollama.py ./checkpoints/checkpoint-1

# Option 2: Import manually (make sure you have run `ollama pull qwen3.5:0.8b`)
cd ./checkpoints/checkpoint-1
cat > Modelfile <<'EOF'
FROM qwen3.5:0.8b
ADAPTER .

SYSTEM """
You are her caring boyfriend/husband. She just sent a message. Please reply in English.
First acknowledge her emotions, then gently ask or express support;
do not blame, lecture, say "calm down" or "what's the big deal";
be warm and sincere, keep it under 150 words.
"""

PARAMETER temperature 0.7
PARAMETER top_p 0.9
PARAMETER num_ctx 2048
EOF
ollama create relationship-chat -f Modelfile
```

Then chat directly:

```bash
ollama run relationship-chat
```

Or use the Python client provided in this project:

```bash
python3 chat.py
```

Sample interaction:

```text
Her: You forgot our anniversary again. Do you even care about me?
You: I'm sorry, I messed up again. The anniversary means a lot to me, and I hate that I let you down. Let's make it up tonight, okay?

Her: Your game is so loud. Can't you spend some time talking to me?
You: Sure, I'll turn it down right now. What do you want to talk about? I'm here.
```

## Tuning Tips

You can adjust these in the `trainer` service environment variables in `docker-compose.yml`:

| Variable | Default | Description |
|------|--------|------|
| `MODEL_NAME` | `Qwen/Qwen3.5-0.8B` | actor/critic training model |
| `ARENA_LLM_MODEL` | `qwen3.5:0.8b` | Ollama rollout model |
| `NUM_ITERATIONS` | 1 | number of training iterations; more usually yields higher success |
| `BATCH_SIZE` | 1 | number of scenarios sampled per iteration |
| `PPO_EPOCHS` | 1 | PPO update epochs per iteration |
| `LEARNING_RATE` | 2e-5 | learning rate |
| `MAX_PROMPT_LEN` | 64 | max prompt length |
| `MAX_RESPONSE_LEN` | 64 | max reply length |
| `ARENA_AGENT_MAX_TOKENS` | 64 | max generation length when the agent calls the LLM |

If memory is insufficient, reduce `MAX_PROMPT_LEN`, `MAX_RESPONSE_LEN`, and `BATCH_SIZE` further.

## Extensions

- **Change scenarios**: Edit `SCENARIOS` in `data/build_dataset.py`, add real "pitfall conversations" from your relationship, regenerate `scenarios.jsonl`, and retrain.
- **Change scoring rules**: Adjust the `must_avoid` / `must_include` weights in `verify/score_response.py`, or add new dimensions (such as reply length, whether it asks a question, etc.).
- **Swap base model**: This example defaults to `Qwen/Qwen3.5-0.8B` as the actor model. If you want to use another Qwen/Llama/Mistral model, as long as Ollama supports `ADAPTER` import for that architecture, it will work.

## Troubleshooting

**Ollama model pull fails**

```bash
docker compose exec ollama ollama pull qwen3.5:0.8b
```

**Dashboard does not show success rate**

Confirm that port 9091 for `openagora-server` is mapped and visit `http://localhost:9091`.

**Training reward stays at 0**

Check that `score_response.py` correctly writes to `/sandbox/.arena/rewards.jsonl` and that `ARENA_VERIFY_COMMAND` points to `/app/score_response.py`.

**Ollama adapter import fails**

Confirm that the checkpoint directory contains `adapter_config.json` and `adapter_model.safetensors`, and that you have run `ollama pull qwen3.5:0.8b` locally.

## License

This example uses the same license as the main repository.
