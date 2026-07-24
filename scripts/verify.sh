#!/usr/bin/env bash
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"

source "$REPO_ROOT/.venv/bin/activate"
cd "$REPO_ROOT"
python -m pytest -q
exit $?
