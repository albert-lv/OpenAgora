# Arena × SWE-agent Integration

This example demonstrates how to integrate SWE-agent into Arena for SWE-bench-style code repair tasks.

## Prerequisites

- Docker + Docker Compose
- Go 1.25+
- Python 3.10+
- Ollama or vLLM (as the LLM backend)

## Quick Start

### 1. Start Arena Server

```bash
cd /path/to/OpenAgora
make build
./bin/openagora-server --sandbox=docker
```

### 2. Start LLM Backend

**Option A: Ollama (Recommended)**
```bash
ollama pull qwen3.5:0.8b
ollama serve
```

**Option B: vLLM**
```bash
vllm serve Qwen/Qwen3.5-0.8B --enable-auto-tool-choice
```

### 3. Build SWE-agent Image

```bash
cd examples/swe-agent
./run.sh
```

### 4. View Results

```bash
# Sample output
Rollout created: rollout-xxx
Status: success
Reward: 1.0
Trajectory steps: 12
```

## Configuration

The `env_vars` in `task.json` control agent behavior:

| Variable | Description | Default |
|------|------|--------|
| `USE_LLM` | Whether to let the LLM try generating a patch (`1` enabled) | `1` |
| `ARENA_MODEL` | Model name used (via Arena LLM proxy) | `qwen2.5-coder:1.5b` |
| `LLM_MAX_TURNS` | Maximum number of LLM attempts | `3` |

### Disable Golden Patch Fallback

The current demo ensures stable completion with a 1.5B local model by falling back to the dataset's `golden_patch` when the LLM fails to generate a patch that passes tests. With a stronger model (e.g., GPT-4o), you can disable fallback:

```bash
python3 prepare_task.py --instance-id pallets__flask-4045
python3 - <<'PY'
import json
with open("task.json") as f:
    task = json.load(f)
task["env_vars"]["NO_GOLDEN_FALLBACK"] = "1"
with open("task.json", "w") as f:
    json.dump(task, f, indent=2)
PY
./run.sh
```

> Note: After disabling fallback, if the LLM fails to generate a patch that passes tests, the rollout will end with failed.

### Enable Structured Tool Agent

By default, the LLM mode lets the model directly output bash code blocks to edit files. Set `USE_TOOLS=1` to switch to structured tool mode, where the LLM outputs JSON tool calls (`view` / `edit` / `bash` / `finish`) and views files before editing each round:

```bash
USE_TOOLS=1 ARENA_MODEL=qwen2.5:3b LLM_MAX_TURNS=3 \
    python3 benchmark.py --use-llm --no-fallback \
    --instances pallets__flask-4045 \
    --output benchmark_results_tools.json
```

## Benchmark Report

The English benchmark report (covering environment, instances, results, and reproduction commands) is in [BENCHMARK.md](BENCHMARK.md).

## Batch Validation

`benchmark.py` can run validation on multiple SWE-bench Lite instances simultaneously:

```bash
# Golden-patch mode (no LLM call, validate Arena pipeline)
python3 benchmark.py \
    --instances pallets__flask-4045 django__django-11039 sympy__sympy-12236 \
                scikit-learn__scikit-learn-10949 pytest-dev__pytest-5103 \
    --output benchmark_results_golden.json

# LLM mode + golden fallback disabled (test model's real patch ability)
ARENA_MODEL=qwen2.5:3b LLM_MAX_TURNS=3 \
    python3 benchmark.py --use-llm --no-fallback \
    --instances pallets__flask-4045 \
    --output benchmark_results_llm.json

# Only verify whether prepare_task.py can generate correct task.json for multiple instances (no container)
python3 benchmark.py --dry-run \
    --instances pallets__flask-4045 django__django-11039 \
    --output benchmark_results_dryrun.json
```

## Custom Tasks

Edit the following fields in `task.json`:
- `repository`: GitHub repository URL
- `commit`: Target commit hash (must exist)
- `test_command`: Command used to verify whether the fix is successful
