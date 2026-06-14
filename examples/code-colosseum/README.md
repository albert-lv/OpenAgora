# Code Colosseum — RL Arena Demo

A **professional, end-to-end RL Arena demo** built on top of `agent-arena`.

Two AI agents enter isolated Docker sandboxes, solve the same algorithmic
problem, and are scored by hidden test suites. A modern React dashboard streams
the duel live, tracks Elo rankings, and monitors RL training curves.

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

### 1. Build and run everything

```bash
cd /path/to/agent-arena
docker compose -f examples/code-colosseum/docker-compose.yml up --build
```

The stack includes the RL trainer by default. It uses `Qwen/Qwen2.5-0.5B-Instruct`
for a CPU-friendly demo; on first run it downloads the model from HuggingFace.

### 2. Open the dashboard

http://localhost:3000

### 3. Watch training

The **Training** tab shows live reward/loss/KL curves. The trainer writes metrics
to the shared data volume and the orchestrator serves them to the dashboard.

### 4. Start a duel

- Go to the **Arena** tab.
- Pick a problem and two agent names.
- Click **Start Duel**.
- Watch the Arena Stage update in real time: Monaco Editor panes show each
  agent's generated code, test progress appears in the battle log, and the
  winner updates the Elo leaderboard.

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

- **Arena Stage** — Monaco Editor panes for each agent's live generated code,
  test progress, and battle log.
- **Leaderboard** — Elo ratings and win/loss/draw records.
- **Training Monitor** — reward/loss/KL curves.

### RL Trainer

`training/train_colosseum.py` is a CPU-friendly PPO skeleton that samples
problems from the bank, runs Arena rollouts, shapes rewards, and updates a
LoRA-tuned language model. It writes metrics to `/app/data/metrics.jsonl` for
the dashboard.

The `trainer` service is enabled by default in `docker-compose.yml` and uses
`Qwen/Qwen2.5-0.5B-Instruct` to stay within typical CPU/memory budgets. Increase
`BATCH_SIZE`, `PPO_EPOCHS`, or swap to a larger `MODEL_NAME` when running on
hardware with more memory.

## Development

Run the backend locally:

```bash
cd examples/code-colosseum/backend
pip install -e ../../../python/openagora-sdk
pip install -r requirements.txt
PROBLEMS_DIR=../problems uvicorn backend.main:app --reload --port 8080
```

Run the dashboard locally:

```bash
cd examples/code-colosseum/dashboard
npm install
npm run dev
```

## Extending the Demo

- Add problems by creating new directories under `problems/`.
- Swap `mock-llm` for a real backend (vLLM, SGLang, Ollama) by setting
  `ARENA_LLM_BACKEND`.
- Implement GRPO by extending `training/train_colosseum.py` with group-relative
  advantage estimation.
- Add Monaco Editor by replacing the code `<pre>` blocks in
  `dashboard/src/components/ArenaStage.tsx`.
