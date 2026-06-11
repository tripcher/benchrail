# Python Benchmark Image

`docker/python` contains a Python-focused Docker image for running `benchrail` benchmarks in a
smaller environment than the universal image.

This image keeps the same overall approach as `docker/universal`:

- preinstall supported runtime versions in the image
- select the active Python version at container startup through `BENCH_ENV_PYTHON_VERSION`
- install agent CLIs at startup through `BENCH_ENV_CODEX_VERSION` and
  `BENCH_ENV_CLAUDE_CODE_VERSION`
- run setup scripts from the image entrypoint before executing the requested command

## Build

```sh
docker build \
    -f docker/python/Dockerfile \
    -t benchrail-python:latest \
    .
```

## Runtime configuration

- `BENCH_ENV_PYTHON_VERSION`: Python version to activate with `pyenv`
- `BENCH_ENV_CODEX_VERSION`: Codex CLI version to install with `npm`
- `BENCH_ENV_CLAUDE_CODE_VERSION`: Claude Code CLI version to install with `npm`

The image includes Python `3.10`, `3.11`, `3.12`, `3.13`, and `3.14`, plus `uv`, `poetry`.

Node.js is included only to support agent CLI installation.
