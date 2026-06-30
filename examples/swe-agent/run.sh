#!/usr/bin/env bash
set -euo pipefail

# Arena × SWE-agent Integration Example
# Runs a single real SWE-bench Lite rollout through Arena.
#
# Usage:
#   ./run.sh                              # use default SWE-bench instance
#   SWE_INSTANCE_ID=sympy__sympy-12345 ./run.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$SCRIPT_DIR/../.."
ARENA_ENDPOINT="${ARENA_ENDPOINT:-localhost:9090}"
TASK_FILE="${TASK_FILE:-$SCRIPT_DIR/task.json}"
SWE_INSTANCE_ID="${SWE_INSTANCE_ID:-pallets__flask-4045}"

cd "$SCRIPT_DIR"

# Prepare task.json from the SWE-bench Lite dataset.
echo "Preparing SWE-bench task $SWE_INSTANCE_ID ..."
python3 "$SCRIPT_DIR/prepare_task.py" \
    --instance-id "$SWE_INSTANCE_ID" \
    --output "$TASK_FILE"

# Read the official SWE-bench image from the generated task.
BASE_IMAGE="$(python3 -c "import json; print(json.load(open('$TASK_FILE'))['sandbox_image'])")"
echo "Official SWE-bench image: $BASE_IMAGE"

# Sanity checks.
if ! docker info >/dev/null 2>&1; then
    echo "Error: Docker daemon is not running or not accessible" >&2
    exit 1
fi

# Ensure the official image is available locally.
if ! docker image inspect "$BASE_IMAGE" >/dev/null 2>&1; then
    echo "Pulling $BASE_IMAGE ..."
    docker pull "$BASE_IMAGE"
fi

# Build the Arena wrapper image on top of the official SWE-bench image.
# Default to a per-instance tag so multiple instances can be built/pulled in parallel
# without overwriting each other's base image layers.
WRAPPER_IMAGE="${WRAPPER_IMAGE:-openagora-swe-agent:$SWE_INSTANCE_ID}"
SKIP_BUILD="${SKIP_BUILD:-0}"

if [[ "$SKIP_BUILD" == "1" ]] && docker image inspect "$WRAPPER_IMAGE" >/dev/null 2>&1; then
    echo "$WRAPPER_IMAGE already exists; skipping build (set SKIP_BUILD=0 to force rebuild)"
else
    echo "Building $WRAPPER_IMAGE wrapper image..."
    # Note: Docker's local layer cache is used automatically; --cache-from is
    # omitted because it can hang when the referenced manifest is not present.
    docker build \
        --build-arg "BASE_IMAGE=$BASE_IMAGE" \
        -t "$WRAPPER_IMAGE" \
        -f "$PROJECT_ROOT/docker/Dockerfile.swe-agent" \
        "$PROJECT_ROOT"
fi

# Tell Arena to use the wrapper image (not the bare SWE-bench image) and
# allow environment variables to override task env_vars.
python3 - <<PY
import json
import os

with open("$TASK_FILE", "r+") as f:
    task = json.load(f)
    task["base_image"] = task.get("sandbox_image")
    task["sandbox_image"] = "$WRAPPER_IMAGE"
    env_vars = task.setdefault("env_vars", {})
    for key in ("USE_LLM", "USE_TOOLS", "ARENA_MODEL", "LLM_MAX_TURNS", "NO_GOLDEN_FALLBACK"):
        value = os.environ.get(key)
        if value is not None:
            env_vars[key] = value
    task["env_vars"] = env_vars
    f.seek(0)
    json.dump(task, f, indent=2)
    f.truncate()
PY

echo "Creating SWE-agent rollout via Arena ($ARENA_ENDPOINT)..."
python3 "$SCRIPT_DIR/run_rollout.py" \
    --endpoint "$ARENA_ENDPOINT" \
    --task-file "$TASK_FILE"
