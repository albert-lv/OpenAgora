#!/usr/bin/env bash
set -euo pipefail

# Quickstart: run a single rollout through Arena

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ARENA_ENDPOINT="${ARENA_ENDPOINT:-localhost:9090}"
TASK_FILE="${TASK_FILE:-$SCRIPT_DIR/task.json}"

# Ensure arena-sdk is available
if ! python3 -c "import arena_sdk" 2>/dev/null; then
    echo "Installing arena-sdk..."
    pip install -e "$SCRIPT_DIR/../../python/arena-sdk"
fi

echo "Creating rollout via Arena ($ARENA_ENDPOINT)..."
python3 "$SCRIPT_DIR/run_rollout.py" \
    --endpoint "$ARENA_ENDPOINT" \
    --task-file "$TASK_FILE"
