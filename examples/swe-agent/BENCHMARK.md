# Arena × SWE-agent Benchmark Report

This report documents the validation of the Arena × SWE-agent integration on real SWE-bench Lite instances.

## Environment

- **Host**: macOS, Apple Silicon, 8 GB RAM, 12 CPUs
- **Docker**: Docker Desktop 28.3.2 (HTTP/HTTPS proxy configured to `http://127.0.0.1:YOUR_PROXY_PORT` for image pulls)
- **Arena server**: `bin/openagora-server --sandbox=docker --grpc :9090 --http :9093`
- **LLM backend**: Ollama 0.x with local models (`qwen2.5:3b`, `qwen2.5-coder:1.5b`)
- **Dataset**: `princeton-nlp/SWE-bench_Lite` (Hugging Face)
- **Agent image**: `openagora-swe-agent:<instance_id>` built on top of official `swebench/sweb.eval.x86_64.*` images

## Instances

| Instance | Repository | FAIL_TO_PASS count | Status |
|----------|------------|-------------------:|--------|
| `pallets__flask-4045` | Flask | 2 | ✅ golden patch passes |
| `django__django-11039` | Django | 1 | ✅ golden patch passes |
| `sympy__sympy-12236` | SymPy | 1 | ✅ golden patch passes |
| `scikit-learn__scikit-learn-10949` | scikit-learn | 1 | ✅ golden patch passes |
| `pytest-dev__pytest-5103` | pytest | 1 | ✅ golden patch passes |

All five instances ran end-to-end inside their official SWE-bench Docker images through the Arena rollout → sandbox → verify → reward pipeline.

## Results

### Golden-patch mode (deterministic baseline)

Command:

```bash
python3 benchmark.py \
    --instances pallets__flask-4045 django__django-11039 sympy__sympy-12236 \
                scikit-learn__scikit-learn-10949 pytest-dev__pytest-5103 \
    --output benchmark_results_golden.json
```

Summary: **5/5 passed**.

| Instance | Status | Reward | Elapsed | Notes |
|----------|--------|--------|---------|-------|
| `pallets__flask-4045` | success | 1.0 | ~50s | Applies `golden_patch` + `test_patch`; Arena verify runs pytest and passes. |
| `django__django-11039` | success | 1.0 | ~64s | Uses Django's `runtests.py` entry point. |
| `sympy__sympy-12236` | success | 1.0 | ~68s | SymPy pytest in the testbed conda environment. |
| `scikit-learn__scikit-learn-10949` | success | 1.0 | ~47s | scikit-learn pytest with Python 3.6 testbed. |
| `pytest-dev__pytest-5103` | success | 1.0 | ~50s | pytest self-tests with the custom pytest build. |

This confirms the full Arena pipeline works for real SWE-bench Lite tasks across multiple repositories and test harnesses.

### LLM patch generation without fallback (`NO_GOLDEN_FALLBACK=1`)

| Model | Agent mode | Instance | Status | Reward | Trajectory steps | Tokens | Notes |
|-------|------------|----------|--------|--------|------------------|--------|-------|
| `qwen2.5:3b` | bash-block | `pallets__flask-4045` | success | 0.0 | 3 | prompt=7336, completion=1129 | LLM attempted 3 turns but did not produce a passing patch. |
| `qwen2.5:3b` | tool-use (`USE_TOOLS=1`) | `pallets__flask-4045` | success | 0.0 | 3 | prompt=2383, completion=263 | Tool calls executed correctly (view/edit/finish), but 3b model still failed to fix the issue. |

Observations:

- The `NO_GOLDEN_FALLBACK=1` switch works as intended: when the LLM fails, the rollout ends with `reward=0.0` instead of silently applying the golden patch.
- The bash-block agent consumed more tokens and made more progress in absolute terms, but neither agent mode succeeded with the 3b local model.
- The tool-use agent produced valid JSON tool calls and used `view`/`edit`/`finish` correctly, demonstrating that the structured agent loop is functional.

## How to reproduce

```bash
cd examples/swe-agent
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 1. Golden-patch baseline across 5 instances
python3 benchmark.py \
    --instances pallets__flask-4045 django__django-11039 sympy__sympy-12236 \
                scikit-learn__scikit-learn-10949 pytest-dev__pytest-5103 \
    --output benchmark_results_golden.json

# 2. LLM bash-block agent, no fallback
ARENA_MODEL=qwen2.5:3b LLM_MAX_TURNS=3 \
    python3 benchmark.py --use-llm --no-fallback \
    --instances pallets__flask-4045 \
    --output benchmark_results_llm.json

# 3. Structured tool-use agent, no fallback
USE_TOOLS=1 ARENA_MODEL=qwen2.5:3b LLM_MAX_TURNS=3 \
    python3 benchmark.py --use-llm --no-fallback \
    --instances pallets__flask-4045 \
    --output benchmark_results_tools.json

# 4. Dry-run across multiple repositories (no container execution)
python3 benchmark.py --dry-run \
    --instances pallets__flask-4045 django__django-11039 sympy__sympy-12236 \
                scikit-learn__scikit-learn-10949 pytest-dev__pytest-5103 \
    --output benchmark_results_dryrun.json
```

## Implementation notes

- `prepare_task.py` now parses both pytest node ids (`path/to/test.py::Class::method`) and unittest-style strings (`test_method (module.Class)`) to build a valid `pytest -k` filter.
- For Django it keeps the official `./tests/runtests.py` invocation.
- The entrypoint automatically installs `pytest` into the `testbed` conda environment when it is missing (some SWE-bench images do not include it).

## Known limitations

1. **Local model capacity**: `qwen2.5:3b` is not strong enough to consistently generate correct patches for SWE-bench Lite issues. Stronger models (e.g., GPT-4o, Claude 3.5 Sonnet, or larger local models) are expected to perform better.
2. **Sample size**: Five instances validate the integration, but a broader benchmark across 10–50 instances with stronger models is the next step.
3. **Tool-use maturity**: The JSON tool-use agent is functional but minimal. Richer tooling (grep, file tree, diagnostics) and better error recovery would further improve success rates.
4. **macOS GPU training**: The veRL training loop requires an NVIDIA GPU; it has been script-tested but not executed on this Apple-Silicon machine.

## Next steps

- Run the same benchmark with GPT-4o or Claude 3.5 Sonnet via `NO_GOLDEN_FALLBACK=1` to establish a real LLM patch-generation baseline.
- Pre-pull or cache SWE-bench images for the top 20 SWE-bench Lite instances and run end-to-end validation.
- Extend the tool-use agent with more tools (grep, file tree, git diff) and iterative error recovery.
- Connect the SWE-agent demo to the veRL training loop for end-to-end RL training on code repair tasks.
