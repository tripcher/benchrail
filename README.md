# benchrail

CLI for benchmarking agent setups.

`benchrail` is a simple CLI for running the same tasks across different agent
setups and comparing the results.

An agent setup can include:

- a different agent (Codex, Claude code)
- a different model
- a different skill
- a different tool
- a different `AGENTS.md`
- a different prompt or context-engineering strategy
- a different execution environment

Use `benchrail` to measure whether a change actually makes the agent better on
the tasks you care about.

## Quick Start

### Install

Install from PyPI with `uv`:

```bash
uv tool install benchrail
```

Install from PyPI with `pip`:

```bash
pip install benchrail
```

### Run
Run in Docker mode:

```bash
benchrail run \
  --dataset examples/multi-swe-bench-universal-smoke \
  --mode docker
```

Run the same dataset locally:

```bash
benchrail run \
  --dataset examples/multi-swe-bench-universal-smoke \
  --mode local 
```

If you use Docker mode and want to reuse your local AI agent login instead of passing
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
benchrail validate \
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
[LICENSES/LICENSE](./LICENSES/LICENSE).

This repository also contains third-party derived materials:

- `docker/universal/` was adapted in part from
  `https://github.com/openai/codex-universal` (MIT)
- `examples/multi-swe-bench-universal-smoke/` is derived from `SWE-bench_Lite`
  and `SWE-bench_Multilingual`

See [LICENSES/THIRD_PARTY.md](./LICENSES/THIRD_PARTY.md) for attribution and
redistribution caveats for dataset-derived content.
