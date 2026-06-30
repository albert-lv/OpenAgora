#!/usr/bin/env bash
# Apply OpenAgora compatibility patches to the installed veRL package.
#
# Usage:
#   bash docs/apply_verl_fixes.sh
#   bash docs/apply_verl_fixes.sh --check

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

cd "${SCRIPT_DIR}/.."

if ! python3 -c "import verl" 2>/dev/null; then
    echo "ERROR: veRL is not installed in the current Python environment." >&2
    echo "Activate the OpenAgora virtual environment and try again." >&2
    exit 1
fi

exec python3 "${SCRIPT_DIR}/apply_verl_fixes.py" "$@"
