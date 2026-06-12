#!/usr/bin/env bash
set -euo pipefail

# Quickstart: run a single rollout through Arena

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ARENA_ENDPOINT="${ARENA_ENDPOINT:-localhost:9090}"
TASK_FILE="${TASK_FILE:-$SCRIPT_DIR/task.json}"
SDK_DIR="$SCRIPT_DIR/../../python/openagora-sdk"

# Detect project venv if present
if [ -f "$SCRIPT_DIR/../../.venv/bin/python" ]; then
    PYTHON="$SCRIPT_DIR/../../.venv/bin/python"
elif [ -f "$SCRIPT_DIR/../../.venv/bin/python3" ]; then
    PYTHON="$SCRIPT_DIR/../../.venv/bin/python3"
else
    PYTHON="python3"
fi

# Ensure openagora-sdk is available
if ! "$PYTHON" -c "import openagora_sdk" 2>/dev/null; then
    echo "Installing openagora-sdk..."
    if command -v uv &>/dev/null; then
        # Prefer uv if the project uses it
        uv pip install -e "$SDK_DIR"
    elif "$PYTHON" -m pip --version &>/dev/null; then
        # Standard PEP 668 compatible path
        "$PYTHON" -m pip install -e "$SDK_DIR"
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
"$PYTHON" "$SCRIPT_DIR/run_rollout.py" \
    --endpoint "$ARENA_ENDPOINT" \
    --task-file "$TASK_FILE"
