# Python Benchmark Image

`docker/python` contains a Python-focused Docker image for running `benchrail` benchmarks in a
smaller environment than the universal image.

Published images are available on GitHub Container Registry:

- `ghcr.io/tripcher/benchrail-python:latest`
- `ghcr.io/tripcher/benchrail-python:<release-tag>`

Use a release tag for reproducible benchmark reports. Use `latest` for local smoke testing.

This image keeps the same overall approach as `docker/universal`:

- preinstall supported runtime versions in the image
- select the active Python version at container startup through `BENCH_ENV_PYTHON_VERSION`
- install agent CLIs at startup through `BENCH_ENV_CODEX_VERSION` and
  `BENCH_ENV_CLAUDE_CODE_VERSION`
- run setup scripts from the image entrypoint before executing the requested command

## Primary Usage

Dataset config example:

```json
{
  "docker": {
    "image": "ghcr.io/tripcher/benchrail-python:latest",
    "env": {
      "BENCH_ENV_PYTHON_VERSION": "3.12"
    }
  }
}
```

Docker pulls the image automatically when a task starts and the image is not available
locally. You can also pull it explicitly:

```sh
docker pull ghcr.io/tripcher/benchrail-python:latest
```

## Local Image Development

Build the image locally only when changing files under `docker/python/`:

```sh
docker build \
    -f docker/python/Dockerfile \
    -t benchrail-python:dev \
    .
```

## Runtime configuration

- `BENCH_ENV_PYTHON_VERSION`: Python version to activate with `pyenv`
- `BENCH_ENV_CODEX_VERSION`: Codex CLI version to install with `npm`
- `BENCH_ENV_CLAUDE_CODE_VERSION`: Claude Code CLI version to install with `npm`

The image includes Python `3.10`, `3.11`, `3.12`, `3.13`, and `3.14`, plus `uv`, `poetry`.

Node.js is included only to support agent CLI installation.
