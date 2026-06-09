# benchrail

CLI for benchmarking agent setups.

`benchrail` is a simple CLI for running the same tasks across different agent
setups and comparing the results.

An agent setup can include:

- a different agent
- a different model
- a different skill
- a different tool
- a different `AGENTS.md`
- a different prompt or context-engineering strategy
- a different execution environment

Use `benchrail` to measure whether a change actually makes the agent better on
the tasks you care about.

## What It Does

- Expands a dataset into `(instance, agent)` tasks
- Runs tasks in `local` or `docker` mode
- Captures agent output, checks, timing, token usage, and cost metadata
- Writes per-task results and aggregated run summaries

Typical use cases:

- Compare Codex and Claude Code on the same dataset
- Test whether a new skill improves results on specific tasks
- Measure whether a tool or `AGENTS.md` change helps or hurts
- Smoke-test a benchmark dataset across multiple language ecosystems
- Compare agent setups with repeatable local or containerized runs

## Quick Start

Requirements:

- Python 3.10+
- [`uv`](https://docs.astral.sh/uv/)
- Docker, if you want `--mode docker`

Install dependencies:

```bash
uv sync --dev
```

Validate the included smoke dataset:

```bash
uv run benchrail validate \
  --dataset examples/multi-swe-bench-universal-smoke
```

Run the included smoke dataset in Docker mode:

```bash
uv run benchrail run \
  --dataset examples/multi-swe-bench-universal-smoke \
  --mode docker \
  --agents codex-gpt-5.4-mini-medium
```

Run the same dataset locally:

```bash
uv run benchrail run \
  --dataset examples/multi-swe-bench-universal-smoke \
  --mode local \
  --agents codex-gpt-5.4-mini-medium
```

If you use Docker mode and want to reuse your local Codex login instead of passing
an API key into the container, add:

```bash
--auth-session
```

## First-Look Mental Model

The workflow is intentionally simple:

1. Create or choose a dataset directory
2. Validate it with `benchrail validate`
3. Run it against one or more agents with `benchrail run`
4. Inspect per-task JSON results, logs, and the aggregated run summary

At runtime, the tool builds the cartesian product of:

- dataset instances
- manifest agents

That becomes the task queue for the run.

## Core Concepts

### Dataset

A dataset is a directory containing:

- a `manifest.json` file describing which agents to run
- an optional `config.json` and `environment/` directory containing instance defaults
- one subdirectory per benchmark instance

### Instance

Each instance contains a `config.json` plus optional environment scripts and patches.

### Agent

An agent entry in `manifest.json` maps an agent id to an adapter and optional CLI
arguments such as model selection.

## Dataset Layout

Expected dataset shape:

```text
<dataset>/
  manifest.json
  config.json
  environment/
    Dockerfile
    setup.sh
  <instance_id>/
    config.json
    environment/
      Dockerfile
      setup.sh
      run-gold-tests.sh
      any_check.sh
    patches/
      test.patch
```

Dataset `config.json` fields are inherited by each instance. Nested Docker environment
values, hooks, and named check commands are merged, while explicit instance values override
dataset defaults.

Dataset `environment/` files are copied first, then instance `environment/` files are copied
on top. For an inherited Dockerfile such as `"dockerfile": "environment/Dockerfile"`, the
instance path is used when it exists; otherwise Benchrail falls back to the dataset path.
An explicit instance `docker.image` overrides an inherited Dockerfile, and an explicit
instance `docker.dockerfile` overrides an inherited image.

Example included in this repository:

- `examples/multi-swe-bench-universal-smoke`

Validate it before your first run:

```bash
uv run benchrail validate \
  --dataset examples/multi-swe-bench-universal-smoke
```

## Example `manifest.json`

```json
{
  "agents": [
    {
      "id": "codex-gpt-5.4-mini-medium",
      "agent": "codex",
      "version": "latest",
      "command": "--model gpt-5.4-mini --config model_reasoning_effort=\"medium\" --disable fast_mode"
    }
  ]
}
```

Current built-in agent types:

- `codex`
- `claude-code`

## CLI Commands

### `validate`

Checks dataset structure and validates all configuration files.

```bash
uv run benchrail validate --dataset path/to/dataset
```

### `run`

Runs all `(instance, agent)` tasks produced from the dataset and manifest.

```bash
uv run benchrail run \
  --dataset path/to/dataset \
  --mode docker
```

Useful options:

- `--agents`: comma-separated agent ids from `manifest.json`
- `--instance_ids`: comma-separated instance ids to run
- `--workspace`: workspace root for task execution directories
- `--output`: directory for result artifacts
- `--logs`: directory for runner and step logs
- `--run_id`: explicit run identifier
- `--workers`: maximum parallel workers
- `--auth-session`: in Docker mode, copy a local auth session file into the task container

## Execution Modes

### `local`

Use local mode when the host machine already has the right toolchains and agent CLI
access.

Pros:

- Faster iteration
- No container setup
- Easier local debugging

Tradeoffs:

- Depends on host environment consistency
- Harder to make fully reproducible across machines

### `docker`

Use Docker mode when you want a more reproducible execution environment or need the
provided universal image flow.

Pros:

- Better environment isolation
- Better fit for multi-language benchmark runs
- Easier to standardize across machines and CI

Tradeoffs:

- Requires Docker
- Adds image and container overhead

## Output Artifacts

By default, result artifacts are written under the run workspace. If `--output` is
provided, result JSON and CSV summaries are written there instead.

Aggregated run artifacts:

```text
<output-or-workspace>/<run_id>/
  result.json
  result.csv
```

Per-task artifacts:

```text
<output-or-workspace>/<run_id>/<agent_id>/<instance_id>/
  result.json
  agent.patch
```

Per-task logs:

```text
<logs-root>/<run_id>/<agent_id>/<instance_id>/
  runner.log
  logs/
    agent.stdout
    agent.stderr
    check_<name>.stdout
    check_<name>.stderr
    ...
```

The aggregated run summary includes:

- passed / failed / total tasks
- total duration
- token counts, when available
- cost in USD and credits, when available
- per-check pass/fail counts

## Included Example Dataset

The repository includes a smoke dataset built for cross-language benchmarking:

- `examples/multi-swe-bench-universal-smoke`

It is intended primarily for Docker runs with the universal benchmark image and
includes instances across multiple ecosystems.

Run it:

```bash
uv run benchrail run \
  --dataset examples/multi-swe-bench-universal-smoke \
  --mode docker
```

More context is available in:

- `examples/multi-swe-bench-universal-smoke/README.md`

## Development

Run unit tests:

```bash
make unit
```

Run lint and type checks:

```bash
make lint
```

Format the codebase:

```bash
make format
```

Equivalent direct commands:

```bash
uv run pytest tests/unit/ -v
uv run ruff check benchrail/ tests/
uv run mypy benchrail tests
uv run ruff format benchrail/ tests/
uv run ruff check --fix benchrail/ tests/
```

## License

The source code in this repository is licensed under the MIT License. See
[LICENSE](LICENSE) or
[LICENSES/LICENSE](LICENSES/LICENSE).

This repository also contains third-party derived materials:

- `docker/universal/` was adapted in part from
  `https://github.com/openai/codex-universal` (MIT)
- `examples/multi-swe-bench-universal-smoke/` is derived from `SWE-bench_Lite`
  and `SWE-bench_Multilingual`

See [NOTICE](NOTICE) for
an overview, and
[LICENSES/THIRD_PARTY.md](LICENSES/THIRD_PARTY.md)
for attribution and redistribution caveats for dataset-derived content.

## Repository Structure

```text
benchrail/
  cli.py
  commands/
  dto/
  adapters/
  runner/

tests/
  unit/
  integration/

docker/universal/
examples/
```

## When To Reach For This Tool

Use `benchrail` when you need:

- repeatable benchmark runs against coding agents
- stable task expansion from dataset definitions
- structured pass/fail artifacts instead of raw terminal logs
- token and cost reporting normalized into result files

It is less suitable if you only need a one-off ad hoc script or a single manual
agent run with no result collection.
