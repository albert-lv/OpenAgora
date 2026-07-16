# Arena Task Format

Arena tasks can be defined in two ways:

1. **Legacy `task.json`** — a single JSON file passed verbatim to the sandbox.
2. **New `task.toml` directory** — a Harbor-style task bundle with `task.toml`, `instruction.md`, `environment/`, and `tests/`.

The `arena` CLI converts the directory format into the legacy `task.json` automatically.

## Directory Layout

```text
tasks/hello-world/
├── task.toml          # Task metadata, environment, agent, verifier config
├── instruction.md     # Prompt / instructions shown to the agent
├── environment/       # Dockerfile, docker-compose.yaml, or referenced image
└── tests/             # Verification scripts and reward definitions
    └── test_hello.py
```

## `task.toml` Schema

```toml
schema_version = "1.0"

[task]
name = "hello-world"
description = "Write a function that returns 'hello, world!'."

[environment]
image = "openagora-agent-minimal:latest"
memory = "1g"
cpus = 1.0
timeout_seconds = 300
env_vars = { KEY = "value" }

[agent]
name = "arena-minimal"
model = "gpt-4o"
max_turns = 10

[verifier]
command = "python -c \"import solution; assert solution.hello() == 'hello, world!'\""
framework = "script"
timeout_seconds = 60
```

### Sections

- `task` — metadata displayed by `arena dataset list`.
- `environment` — sandbox image, resource limits, env vars, and timeout.
- `agent` — agent adapter name and per-agent settings.
- `verifier` — verification command and framework (pytest, unittest, script, or swe-bench-style).
- `artifacts` — optional files to collect after the rollout.

## Multi-Reward Tasks

The verification plane supports multiple named rewards. The agent can write rewards to `/sandbox/.arena/rewards.jsonl`:

```json
{"name": "correctness", "value": 1.0, "weight": 0.7, "source": "agent"}
{"name": "style", "value": 0.8, "weight": 0.3, "source": "agent"}
```

The server aggregates them into a `total_reward`.

You can also declare rewards declaratively in `tests/reward.toml`:

```toml
[[reward]]
name = "correctness"
weight = 0.7
command = "python -m pytest tests/correctness"
aggregation = "mean"

[[reward]]
name = "style"
weight = 0.3
command = "python -m flake8 /sandbox/solution.py"
aggregation = "all_pass"
```

See `examples/cookbook/reward-toml.md` for a complete example.

## Migration from `task.json`

The CLI accepts both formats:

```bash
arena run --task examples/quickstart/task.json
arena run --task examples/tasks/hello-world
```

To migrate an existing `task.json`, create a `task.toml` from its fields and move the prompt to `instruction.md`.
