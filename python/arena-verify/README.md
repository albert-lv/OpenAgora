# Arena Verify

Verification plugins and runners for [Agent Arena](https://github.com/albert-lv/agent-arena).

This package contains the decoupled verification plane used to compute rewards after an agent rollout completes. The primary runner is pytest-based, allowing you to express verification logic as ordinary test cases.

---

## Installation

```bash
cd python/arena-verify
uv sync
```

Requires Python 3.10 or later.

---

## What is Verification?

In Arena, verification is the step that runs after an agent signals completion. It inspects the sandbox state, runs tests, checks outputs, or invokes custom evaluators to produce one or more reward signals.

Because verification is decoupled from the agent itself, you can:

- Reuse the same evaluator across different agents
- Switch evaluators without changing the agent
- Version reward functions alongside your tasks

---

## pytest Runner

The pytest runner executes a test suite inside the sandbox (or against exported artifacts) and converts test outcomes into reward values.

Typical workflow:

1. Agent finishes and writes `/sandbox/.arena/done`
2. Arena invokes `arena_verify.pytest_runner.run(...)`
3. Reward signals are emitted and attached to the rollout

---

## Writing Verifiers

A verifier is just a pytest test. For example:

```python
def test_output_exists():
    assert (Path("/sandbox/output.txt")).exists()

def test_output_format():
    data = json.loads(Path("/sandbox/output.txt").read_text())
    assert "answer" in data
```

The runner maps pass/fail results to scalar rewards and returns them to Arena.

---

## Development

```bash
uv sync --extra dev
uv run pytest
```

---

## License

Apache-2.0 — see the [project license](../../LICENSE) for details.
