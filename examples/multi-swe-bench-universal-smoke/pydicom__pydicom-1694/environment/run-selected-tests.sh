#!/bin/sh
set -eu

VENV_DIR="$BENCH_ENV_DIR/venv"
"$VENV_DIR/bin/pytest" \
  pydicom/tests/test_json.py::TestDataSetToJson::test_suppress_invalid_tags \
  pydicom/tests/test_json.py::TestDataSetToJson::test_roundtrip
