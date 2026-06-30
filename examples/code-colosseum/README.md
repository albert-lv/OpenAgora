# Code Colosseum — RL Arena Demo

A **professional, end-to-end RL Arena demo** built on top of `agent-arena`.

Two AI agents enter isolated Docker sandboxes, solve the same algorithmic
problem, and are scored by hidden test suites. A modern React dashboard streams
the duel live, tracks Elo rankings, and monitors a **real GRPO training loop**
that serves the current policy as the LLM backend — so each update is reflected
in the next generation and rewards improve over iterations.

## Architecture

```
Browser
   │
   ▼ HTTP / SSE
Code Colosseum Dashboard  (React + Vite + Recharts)
   │
   ▼ HTTP / SSE
Colosseum Orchestrator    (FastAPI)
   │ gRPC
Arena Server              (Go, :9090)
   │
   ├── Docker Sandbox A   → solution.py + hidden_tests.py
   └── Docker Sandbox B   → solution.py + hidden_tests.py
   │
   ▼ HTTP
GRPO Trainer              (PyTorch + transformers)
   │
   └── Policy LLM Server  ← actor model being trained
```

## Directory Layout

```
examples/code-colosseum/
├── docker-compose.yml              # one-command full stack
├── problems/                       # problem bank (JSON + tests)
│   ├── two-sum/
│   ├── reverse-string/
│   └── longest-common-prefix/
├── agent/                          # sandbox agent + mock LLM
├── backend/                        # FastAPI orchestrator
├── dashboard/                      # React dashboard
├── training/                       # PPO/GRPO trainer skeleton
└── scripts/                        # dataset generator
```

## Quick Start

### 0. Download the model (first time only)

The trainer runs in offline mode by default so it does not download weights
inside the container.  Pre-download the model on the host and mount the cache
into Docker:

```bash
cd /path/to/agent-arena
MODEL_NAME=Qwen/Qwen2.5-0.5B-Instruct python3 examples/verl-integration/download_model.py
```

This caches weights to `~/.cache/huggingface`, which `docker-compose.yml`
already mounts into the trainer service.

### 1. Build and run everything

```bash
cd /path/to/agent-arena
docker compose -f examples/code-colosseum/docker-compose.yml up --build
```

The stack includes the RL trainer by default.  It is configured for a CPU-friendly
demo using `Qwen/Qwen2.5-0.5B-Instruct`.  You can change `MODEL_NAME` in
`docker-compose.yml` to any compatible HuggingFace causal LM, e.g.
`Qwen/Qwen3.5-0.8B`, as long as the weights are cached locally.

### 2. Open the dashboard

http://localhost:3000

### 3. Watch training

The **Training** tab shows live reward/loss/KL curves.  By default the trainer
uses the deterministic mock LLM backend, which returns a mix of correct and
buggy solution variants.  This creates non-zero reward variance within each
GRPO group, so the training curves show real learning even on CPU hardware.
Metrics are written to the shared data volume and served to the dashboard.

To switch to the trainer's live policy server, set
`ARENA_LLM_BACKEND=http://trainer:8000/v1` in `docker-compose.yml`.  Because the
server shares the same model object as the trainer, each GRPO update is then
reflected in the next rollout's generations.

### 4. Start a duel

- Go to the **Arena** tab.
- Pick a problem, two agent names, and an **engine** for each agent:
  - **Mock LLM** — deterministic local backend (default, free, no API key).
  - **Claude Code** — Anthropic's `claude` CLI.
  - **OpenAI Codex** — OpenAI's `codex` CLI.
- Click **Start Duel**.
- Watch the Arena Stage update in real time: Monaco Editor panes show each
  agent's generated code, test progress appears in the battle log, and the
  winner updates the Elo leaderboard.

### Claude Code vs OpenAI Codex

To run real agent battles, set your API keys and bring the stack up:

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
export OPENAI_API_KEY="sk-..."
docker compose -f examples/code-colosseum/docker-compose.yml up --build
```

Then choose **Claude Code** for Agent A and **OpenAI Codex** for Agent B and
start a duel.  Each engine is exposed as an OpenAI-compatible LLM backend
(`claude-llm` and `codex-llm`) so the standard Code Colosseum agent can call
the Claude Code or Codex CLI to generate a solution, run the hidden tests, and
report the reward back to the arena.

## Components

### Problem Bank

Each problem lives in `problems/<id>/`:

- `problem.json` — metadata, description, function signature.
- `public_tests.py` — visible examples.
- `hidden_tests.py` — used for scoring.
- `solution.py` — reference solution.

### Sandbox Agent

`agent/code_colosseum_agent.py` is the entrypoint inside each Docker sandbox.
It reads the problem from `/sandbox/.arena/task.json`, calls the LLM proxy,
and writes `solution.py` plus `hidden_tests.py` for verification.

### Orchestrator Backend

`backend/main.py` exposes:

- `GET  /api/problems`
- `GET  /api/problems/{id}`
- `POST /api/duels`
- `GET  /api/duels`
- `GET  /api/duels/{id}`
- `GET  /api/duels/{id}/stream`   (SSE)
- `GET  /api/leaderboard`
- `GET  /api/training/status`

Duel results update an Elo leaderboard stored in `/app/data/elo.json`.

### Dashboard

`dashboard/src/App.tsx` is a React + Tailwind + Recharts SPA with:

- **Command Center** — a cinematic single-screen view combining the
  live Arena Stage, agent code, battle log, and GRPO reward distribution charts.
- **Arena Stage** — Monaco Editor panes for each agent's live generated code,
  test progress, and battle log.
- **Leaderboard** — Elo ratings and win/loss/draw records.
- **Training Monitor** — reward/loss/KL curves and per-group reward distribution.

### RL Trainer

`training/train_colosseum.py` is a CPU-friendly GRPO trainer that samples
problems from the bank, runs Arena rollouts, computes group-relative advantages,
and updates a LoRA-tuned language model. It also starts an **OpenAI-compatible
LLM server** (`training/llm_server.py`) that serves the current actor policy, so
every rollout uses the model being trained in real time. Metrics are written to
`/app/data/metrics.jsonl` for the dashboard.

The `trainer` service is enabled by default in `docker-compose.yml` and uses
`Qwen/Qwen2.5-0.5B-Instruct` to stay within typical CPU/memory budgets. Increase
`NUM_ITERATIONS`, `BATCH_SIZE`, `GROUP_SIZE`, or swap `MODEL_NAME` to a larger
model such as `Qwen/Qwen3.5-0.8B` when running on hardware with more memory.

## Development

Run the backend locally:

```bash
cd examples/code-colosseum/backend
python3 -m venv .venv
source .venv/bin/activate
pip install -e ../../../python/openagora-sdk
pip install fastapi uvicorn pydantic
cd ..
PROBLEMS_DIR=./problems TRAINING_METRICS_PATH=./backend/data/metrics.jsonl \
  uvicorn backend.main:app --host 0.0.0.0 --port 8080
```

Run the trainer / policy LLM server locally:

```bash
cd examples/code-colosseum/training
python3 train_colosseum.py
```

The trainer starts an LLM backend on port `8000` and writes metrics to
`METRICS_PATH` (default `./data/metrics.jsonl`).

Run the dashboard locally:

```bash
cd examples/code-colosseum/dashboard
npm install
npm run dev
```

## Extending the Demo

- Add problems by creating new directories under `problems/`.
- Swap the built-in policy LLM server for an external backend (vLLM, SGLang,
  Ollama) by setting `ARENA_LLM_BACKEND`.
- The mock LLM returns controlled variants by default.  Set `DISABLE_VARIANTS=1`
  on the `mock-llm` service to always return canonical correct solutions.
- Tune the RL loop by changing `NUM_ITERATIONS`, `GROUP_SIZE`, `BATCH_SIZE`,
  `GRPO_EPOCHS`, or `MODEL_NAME`.
