#!/bin/bash --login

set -euo pipefail

echo "Verifying language runtimes ..."

read -ra PYTHON <<< "$PYTHON_VERSIONS"
read -ra NODE   <<< "$NODE_VERSIONS"
read -ra RUST   <<< "$RUST_VERSIONS"
read -ra GO     <<< "$GO_VERSIONS"
read -ra SWIFT  <<< "$SWIFT_VERSIONS"
read -ra RUBY   <<< "$RUBY_VERSIONS"
read -ra PHP    <<< "$PHP_VERSIONS"
read -ra JAVA   <<< "$JAVA_VERSIONS"

max=$(printf "%s\n" \
  ${#PYTHON[@]} \
  ${#NODE[@]} \
  ${#RUST[@]} \
  ${#GO[@]} \
  ${#SWIFT[@]} \
  ${#RUBY[@]} \
  ${#PHP[@]} \
  ${#JAVA[@]} \
  | sort -nr | head -1)

for ((i=max-1; i>=0; i--)); do
  BENCH_ENV_PYTHON_VERSION=${PYTHON[i]:-${PYTHON[0]}} \
  BENCH_ENV_NODE_VERSION=${NODE[i]:-${NODE[0]}} \
  BENCH_ENV_RUST_VERSION=${RUST[i]:-${RUST[0]}} \
  BENCH_ENV_GO_VERSION=${GO[i]:-${GO[0]}} \
  BENCH_ENV_SWIFT_VERSION=${SWIFT[i]:-${SWIFT[0]}} \
  BENCH_ENV_RUBY_VERSION=${RUBY[i]:-${RUBY[0]}} \
  BENCH_ENV_PHP_VERSION=${PHP[i]:-${PHP[0]}} \
  BENCH_ENV_JAVA_VERSION=${JAVA[i]:-${JAVA[0]}} \
  bash -lc '
    printf "\n\nTesting setup_universal with versions:\n"
    env | grep "^BENCH_ENV_" | sort
    printf "\n"
    /opt/benchrail/setup_universal.sh
  '
done

echo "- Python:"
python3 --version
pyenv versions | sed 's/^/  /'

echo "- Node.js:"
node --version
npm --version
pnpm --version
yarn --version
npm ls -g

echo "- Bun:"
bun --version

echo "- Java / Gradle:"
java -version
javac -version
gradle --version | head -n 3
mvn --version | head -n 1

echo "- Swift:"
swift --version

echo "- Ruby:"
ruby --version

echo "- Rust:"
rustc --version
cargo --version

echo "- Go:"
go version

echo "- PHP:"
php --version
composer --version

echo "- Elixir:"
elixir --version
erl -version
erl -eval 'erlang:display(erlang:system_info(otp_release)), halt().' -noshell

echo "All language runtimes detected successfully."

echo "Verifying agents runtimes ..."

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
