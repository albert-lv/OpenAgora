#!/usr/bin/env bash
set -euo pipefail

# Quickstart: run a single rollout through Arena

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ARENA_ENDPOINT="${ARENA_ENDPOINT:-localhost:9090}"
TASK_FILE="${TASK_FILE:-$SCRIPT_DIR/task.json}"
SDK_DIR="$SCRIPT_DIR/../../python/arena-sdk"

# Ensure arena-sdk is available
if ! python3 -c "import arena_sdk" 2>/dev/null; then
    echo "Installing arena-sdk..."
    if command -v uv &>/dev/null; then
        # Prefer uv if the project uses it
        uv pip install -e "$SDK_DIR"
    elif python3 -m pip --version &>/dev/null; then
        # Standard PEP 668 compatible path
        python3 -m pip install -e "$SDK_DIR"
    elif command -v pip3 &>/dev/null; then
        pip3 install -e "$SDK_DIR"
    elif command -v pip &>/dev/null; then
        pip install -e "$SDK_DIR"
    else
        echo "Error: no pip found. Please install Python pip."
        exit 1
    fi
fi

echo "Creating rollout via Arena ($ARENA_ENDPOINT)..."
python3 "$SCRIPT_DIR/run_rollout.py" \
    --endpoint "$ARENA_ENDPOINT" \
    --task-file "$TASK_FILE"
