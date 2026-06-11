#!/bin/bash --login

set -euo pipefail

BENCH_ENV_PYTHON_VERSION=${BENCH_ENV_PYTHON_VERSION:-}

echo "Configuring Python runtime..."

if [ -n "${BENCH_ENV_PYTHON_VERSION}" ]; then
    echo "# Python: ${BENCH_ENV_PYTHON_VERSION}"
    pyenv global "${BENCH_ENV_PYTHON_VERSION}"
fi

python3 --version
