# Cookbook: Multi-Reward with `tests/reward.toml`

OpenAgora supports declarative multi-dimensional scoring via `tests/reward.toml`.

## Task layout

```text
examples/tasks/multi-reward/
├── task.toml
├── instruction.md
└── tests/
    ├── reward.toml
    ├── correctness/
    │   └── ...
    └── style/
        └── ...
```

## `tests/reward.toml` schema

```toml
[[reward]]
name = "correctness"
weight = 0.7
command = "python -c \"import solution; assert solution.hello() == 'hello, world!'\""
aggregation = "all_pass"

[[reward]]
name = "style"
weight = 0.3
command = "python -m py_compile /sandbox/solution.py"
aggregation = "all_pass"
```

Fields:

- `name` — reward dimension name
- `weight` — used when aggregating the total reward
- `command` — verification command for this dimension
- `verifier_dir` — optional directory inside `tests/` (default: use command as-is)
- `aggregation` — `all_pass`, `mean`, or `max`

## Run

```bash
./bin/arena run --env docker --task examples/tasks/multi-reward
```

The server runs each reward's command independently, then aggregates them into a
single `VerificationReport` with multiple `Reward` entries.

## Aggregation modes

- `all_pass` — 1.0 if exit code is 0, else 0.0
- `mean` — parse pytest-style pass ratio, or fall back to all_pass
- `max` — 1.0 if any condition passes, else 0.0
