#!/bin/sh
set -eu

VENV_DIR="$BENCH_ENV_DIR/venv"
PYTHON_BIN="${PYTHON_BIN:-python3}"

if [ ! -d "$VENV_DIR" ]; then
  "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

export PIP_DISABLE_PIP_VERSION_CHECK=1
"$VENV_DIR/bin/python" -m pip install --upgrade pip setuptools wheel
"$VENV_DIR/bin/pip" install -e . pytest
