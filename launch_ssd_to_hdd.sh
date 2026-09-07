#!/bin/zsh

set -euo pipefail

SCRIPT_DIR="${0:A:h}"
SCRIPT_PATH="$SCRIPT_DIR/ssd_to_hdd_migrate.py"
VENV_PY="$SCRIPT_DIR/venv/bin/python"

if [[ ! -f "$SCRIPT_PATH" ]]; then
  echo "Missing script: $SCRIPT_PATH"
  exit 1
fi

PYTHON_BIN="python3"
if [[ -x "$VENV_PY" ]]; then
  PYTHON_BIN="$VENV_PY"
fi

exec "$PYTHON_BIN" "$SCRIPT_PATH"
