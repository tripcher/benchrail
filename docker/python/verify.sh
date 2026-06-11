#!/bin/bash --login

set -euo pipefail

echo "Verifying Python runtimes ..."

read -ra PYTHON <<< "$PYTHON_VERSIONS"

for version in "${PYTHON[@]}"; do
  BENCH_ENV_PYTHON_VERSION="${version}" \
  bash -lc '
    printf "\n\nTesting setup_python with versions:\n"
    env | grep "^BENCH_ENV_" | sort
    printf "\n"
    /opt/benchrail/setup_python.sh
  '
done

echo "- Python:"
python3 --version
pyenv versions | sed "s/^/  /"

echo "- Node.js:"
node --version
npm --version
pnpm --version
yarn --version

echo "Python runtimes detected successfully."

echo "Verifying agent runtimes ..."

BENCH_ENV_CODEX_VERSION=${BENCH_ENV_CODEX_VERSION:-}
BENCH_ENV_CLAUDE_CODE_VERSION=${BENCH_ENV_CLAUDE_CODE_VERSION:-}

if [ -n "${BENCH_ENV_CODEX_VERSION}" ] || [ -n "${BENCH_ENV_CLAUDE_CODE_VERSION}" ]; then
  BENCH_ENV_CODEX_VERSION=${BENCH_ENV_CODEX_VERSION} \
  BENCH_ENV_CLAUDE_CODE_VERSION=${BENCH_ENV_CLAUDE_CODE_VERSION} \
  bash -lc '
    printf "\n\nTesting setup_agents with versions:\n"
    env | grep "^BENCH_ENV_" | sort
    printf "\n"
    /opt/benchrail/setup_agents.sh
  '

  if [ -n "${BENCH_ENV_CODEX_VERSION}" ]; then
    echo "- Codex:"
    codex --version
  fi

  if [ -n "${BENCH_ENV_CLAUDE_CODE_VERSION}" ]; then
    echo "- Claude code:"
    claude --version
  fi

  echo "All agent runtimes detected successfully."
else
  echo "Skipping agent runtime verification; no agent CLI versions were requested."
fi
