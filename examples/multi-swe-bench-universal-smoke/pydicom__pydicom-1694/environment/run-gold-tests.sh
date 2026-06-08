#!/bin/sh
set -eu

VENV_DIR="$BENCH_ENV_DIR/venv"
"$VENV_DIR/bin/pytest" pydicom/tests/test_benchrail_gold_json.py
