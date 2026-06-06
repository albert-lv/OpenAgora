#!/usr/bin/env bash
set -euo pipefail

# Arena × SWE-agent Integration Example
# Runs a single SWE-bench style rollout through Arena.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ARENA_ENDPOINT="${ARENA_ENDPOINT:-localhost:9090}"
TASK_FILE="${TASK_FILE:-$SCRIPT_DIR/task.json}"

# Build the SWE-agent Docker image if needed
echo "Building arena-swe-agent image..."
docker build -t arena-swe-agent:latest -f "$SCRIPT_DIR/../../docker/Dockerfile.swe-agent" "$SCRIPT_DIR/../.."

echo "Creating SWE-agent rollout via Arena ($ARENA_ENDPOINT)..."
python3 "$SCRIPT_DIR/run_rollout.py" \
    --endpoint "$ARENA_ENDPOINT" \
    --task-file "$TASK_FILE"
