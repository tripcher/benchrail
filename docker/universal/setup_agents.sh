#!/bin/bash --login

set -euo pipefail

# Supported env vars:
# - BENCH_ENV_CODEX_VERSION
# - BENCH_ENV_CLAUDE_CODE_VERSION
BENCH_ENV_CODEX_VERSION=${BENCH_ENV_CODEX_VERSION:-}
BENCH_ENV_CLAUDE_CODE_VERSION=${BENCH_ENV_CLAUDE_CODE_VERSION:-}

echo "Configuring agent CLIs..."

if ! command -v npm >/dev/null 2>&1; then
    echo "npm is required to install agent CLIs." >&2
    exit 1
fi

if [ -n "${BENCH_ENV_CODEX_VERSION}" ]; then
    current=

    if command -v codex >/dev/null 2>&1; then
        current=$(codex --version 2>/dev/null | grep -Eo '[0-9]+(\.[0-9]+){1,3}([.-][0-9A-Za-z.-]+)?' | head -n1 || true)
    fi

    echo "# Codex CLI: ${BENCH_ENV_CODEX_VERSION}${current:+ (current: ${current})}"

    if [ "${current}" != "${BENCH_ENV_CODEX_VERSION}" ]; then
        npm install -g --no-fund --no-audit "@openai/codex@${BENCH_ENV_CODEX_VERSION}"
    fi

    codex --version
fi

if [ -n "${BENCH_ENV_CLAUDE_CODE_VERSION}" ]; then
    current=

    if command -v claude >/dev/null 2>&1; then
        current=$(claude --version 2>/dev/null | grep -Eo '[0-9]+(\.[0-9]+){1,3}([.-][0-9A-Za-z.-]+)?' | head -n1 || true)
    fi

    echo "# Claude Code: ${BENCH_ENV_CLAUDE_CODE_VERSION}${current:+ (current: ${current})}"

    if [ "${current}" != "${BENCH_ENV_CLAUDE_CODE_VERSION}" ]; then
        npm install -g --no-fund --no-audit "@anthropic-ai/claude-code@${BENCH_ENV_CLAUDE_CODE_VERSION}"
    fi

    claude --version
fi
