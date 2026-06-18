# Universal Benchmark Image

`docker/universal` contains the reference Docker image for running `benchrail` benchmarks in a
shared multi-language environment.

Published images are available on GitHub Container Registry:

- `ghcr.io/tripcher/benchrail-universal:latest`
- `ghcr.io/tripcher/benchrail-universal:<release-tag>`

Use a release tag for reproducible benchmark reports. Use `latest` for local smoke testing.

This image is the default execution environment for datasets that set
`docker.image=ghcr.io/tripcher/benchrail-universal:latest`. It is intended to:

- provide a reproducible runtime for benchmark tasks across multiple language ecosystems
- install and select toolchain versions through `BENCH_ENV_*` variables
- install agent CLIs such as Codex and Claude Code inside the container
- support both normal `benchrail --mode docker` runs and manual container-based debugging

The image entrypoint runs:

1. `setup_universal.sh`
2. `setup_agents.sh`
3. the requested command, or an interactive login shell if no command is provided

## Primary Usage

The main use case is running benchmark datasets through `benchrail` in `docker` mode with the
published GHCR image.

Dataset config example:

```json
{
  "docker": {
    "image": "ghcr.io/tripcher/benchrail-universal:latest"
  }
}
```

Docker pulls the image automatically when a task starts and the image is not available
locally. You can also pull it explicitly:

```sh
docker pull ghcr.io/tripcher/benchrail-universal:latest
```

Run the example smoke dataset:

```sh
uv run benchrail run \
    --dataset examples/multi-swe-bench-universal-smoke \
    --mode docker
```

When a dataset manifest includes an agent version, `benchrail` maps it to the corresponding
runtime environment variable for this image. For example:

- `{"agent":"codex","version":"latest"}` -> `BENCH_ENV_CODEX_VERSION=latest`
- `{"agent":"claude-code","version":"latest"}` -> `BENCH_ENV_CLAUDE_CODE_VERSION=latest`

Explicit `docker.env` values in the instance config still take precedence.

## Manual Container Usage

This image can also be used directly to run `benchrail` inside the container. That is mainly
useful for local debugging of the benchmark environment.

Create a host directory for benchmark outputs:

```sh
mkdir -p "$PWD/tmp"
```

Run the smoke dataset in `local` mode inside the container with API-key auth:

```sh
docker run --rm -it \
    -e CODEX_API_KEY=<token> \
    -e BENCH_ENV_PYTHON_VERSION=3.10 \
    -e BENCH_ENV_NODE_VERSION=22 \
    -e BENCH_ENV_CODEX_VERSION=latest \
    -v "$PWD/examples/multi-swe-bench-universal-smoke:/datasets/multi-swe-bench-universal-smoke:ro" \
    -v "$PWD/tmp:/results" \
    ghcr.io/tripcher/benchrail-universal:latest \
    bash -lc 'benchrail run \
        --dataset /datasets/multi-swe-bench-universal-smoke \
        --mode local \
        --workspace /tmp/benchrail \
        --logs /results \
        --output /results'
```

Run the same flow with a mounted Codex auth session instead of `CODEX_API_KEY`:

```sh
docker run --rm -it \
    -e BENCH_ENV_PYTHON_VERSION=3.10 \
    -e BENCH_ENV_NODE_VERSION=22 \
    -e BENCH_ENV_CODEX_VERSION=latest \
    -v "$PWD/examples/multi-swe-bench-universal-smoke:/datasets/multi-swe-bench-universal-smoke:ro" \
    -v "$PWD/tmp:/results" \
    -v "$HOME/.codex/auth.json:/root/.codex/auth.json:ro" \
    ghcr.io/tripcher/benchrail-universal:latest \
    bash -lc 'benchrail run \
        --dataset /datasets/multi-swe-bench-universal-smoke \
        --mode local \
        --workspace /tmp/benchrail \
        --logs /results \
        --output /results'
```

Inspect generated artifacts on the host:

```sh
find "$PWD/tmp" -maxdepth 2 -type f | sort
```

## Configuring Language Runtimes

`setup_universal.sh` supports the following environment variables:

| Environment variable | Description | Supported versions | Additional packages |
| --- | --- | --- | --- |
| `BENCH_ENV_PYTHON_VERSION` | Python version to use | `3.10`, `3.11`, `3.12`, `3.13`, `3.14` | `pyenv`, `poetry`, `uv`, `ruff`, `black`, `mypy`, `pyright`, `isort`, `pytest` |
| `BENCH_ENV_NODE_VERSION` | Node.js version to use | `18`, `20`, `22`, `24` | `npm`, `pnpm`, `yarn`, `corepack`, `prettier`, `eslint`, `typescript` |
| `BENCH_ENV_RUST_VERSION` | Rust version to use | `1.83.0`, `1.84.1`, `1.85.1`, `1.86.0`, `1.87.0`, `1.88.0`, `1.89.0`, `1.90.0`, `1.91.1`, `1.92.0`, `1.93.0`, `1.94.0`, `1.95.0` | `cargo`, `rustfmt`, `clippy` |
| `BENCH_ENV_GO_VERSION` | Go version to use | `1.22.12`, `1.23.8`, `1.24.3`, `1.25.1` | `golangci-lint` |
| `BENCH_ENV_SWIFT_VERSION` | Swift version to use | `5.10`, `6.1`, `6.2` | |
| `BENCH_ENV_RUBY_VERSION` | Ruby version to use | `3.2.3`, `3.3.8`, `3.4.4` | |
| `BENCH_ENV_PHP_VERSION` | PHP version to use | `8.2`, `8.3`, `8.4`, `8.5` | `composer` |
| `BENCH_ENV_JAVA_VERSION` | Java version to use | `25`, `24`, `23`, `22`, `21`, `17`, `11` on `amd64`; `25`, `24`, `23`, `22`, `21`, `17` on `arm64` | `gradle`, `maven` |

## Configuring Agent CLIs

`setup_agents.sh` supports the following environment variables:

| Environment variable | Description | Install method |
| --- | --- | --- |
| `BENCH_ENV_CODEX_VERSION` | Version of OpenAI Codex CLI to install | `npm install -g @openai/codex@<version>` |
| `BENCH_ENV_CLAUDE_CODE_VERSION` | Version of Claude Code CLI to install | `npm install -g @anthropic-ai/claude-code@<version>` |

Agent CLI versions can be provided either:

- as Docker build arguments, for example `--build-arg BENCH_ENV_CODEX_VERSION=0.136.0`
- as runtime environment variables, for example `-e BENCH_ENV_CODEX_VERSION=0.136.0`

Build arguments are copied into image environment variables. Runtime `-e` values override the
baked-in defaults.

Agent CLIs are installed after the Node.js version is selected, so they are tied to the active
global npm environment in the container.

## What's Included

In addition to the configurable runtimes above, the image also includes:

- `bun` `1.2.14`
- `bazelisk` / `bazel`
- `erlang` `27.1.2`
- `elixir` `1.18.3`
- C/C++ tooling such as `clang-tidy`, `clang-format`, `cpplint`, `cmakelang`

See [Dockerfile](./Dockerfile) for the full package list.

## Local Image Development

Build the image locally only when changing files under `docker/universal/`:

```sh
docker build \
    -f docker/universal/Dockerfile \
    -t benchrail-universal:dev \
    .
```

## Verification

[verify.sh](./verify.sh) validates:

- preinstalled language runtimes declared in the Docker build arguments
- `setup_universal.sh` across the configured runtime matrix
- `setup_agents.sh` when `BENCH_ENV_CODEX_VERSION` and/or
  `BENCH_ENV_CLAUDE_CODE_VERSION` are provided
