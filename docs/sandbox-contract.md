# Sandbox Contract (v1)

> **This is the most important document in Arena.**

Any agent that follows this contract can run in Arena, regardless of language or framework.

## Contract Requirements

| # | Requirement | Mechanism |
|---|-------------|-----------|
| 1 | Agent process starts | Container entrypoint |
| 2 | All LLM calls go through Arena | `OPENAI_BASE_URL` env var (auto-injected) |
| 3 | Requests are authenticated | `ARENA_ROLLOUT_TOKEN` env var (auto-injected) |
| 4 | Signal completion | Write `/sandbox/.arena/done` or exit 0 |
| 5 | Read task definition | Arena writes `/sandbox/.arena/task.json` |
| 6 | Read verification config | Arena writes `/sandbox/.arena/verify.json` |
| 7 | (Optional) Custom rewards | Append `/sandbox/.arena/rewards.jsonl` |
| 8 | (Optional) Metadata | Write `/sandbox/.arena/meta.json` |

## Directory Layout Inside Sandbox

```
/sandbox/
├── .arena/
│   ├── task.json       # Task definition (injected by Arena)
│   ├── verify.json     # Verification config (injected by Arena)
│   ├── done            # Write this to signal completion
│   ├── rewards.jsonl   # Optional: custom reward signals
│   └── meta.json       # Optional: agent metadata
└── ...                 # Agent workspace
```

## task.json Schema

```json
{
  "task_id": "swe-bench/django-12345",
  "description": "Fix the bug where ...",
  "repository": "https://github.com/django/django",
  "commit": "abc123",
  "test_command": "pytest tests/test_foo.py"
}
```

## done Signal Schema

```json
{
  "status": "success" | "failed" | "abandoned",
  "reason": "optional human-readable summary"
}
```

## rewards.jsonl Format

Each line is a JSON object:

```json
{"type": "task_complete", "value": 1.0, "source": "agent:manual"}
```

## Environment Variables

| Variable | Purpose |
|----------|---------|
| `OPENAI_BASE_URL` | Point to Arena LLM proxy |
| `ARENA_ROLLOUT_TOKEN` | Authenticate rollout requests |
| `ARENA_TASK_ID` | Current task identifier |
| `ARENA_SANDBOX_ID` | Current sandbox identifier |

---

**Language-agnostic. Framework-agnostic. Protocol-agnostic.**
