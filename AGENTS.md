# AGENTS.md

## Overview of project

`benchrail` is a Python CLI for running benchmark tasks against coding agents and collecting comparable results.

The core workflow is:
1. Validate a dataset directory containing `manifest.json` and per-instance `config.json` files.
2. Expand the dataset into `(instance, agent)` tasks.
3. Run each task in `local` or `docker` mode.
4. Capture agent output, checks, timing, token usage, and cost metadata.
5. Write per-task outputs plus aggregated run summaries.

Primary use cases in this repository:
- evaluate Codex and Claude Code against benchmark instances
- run smoke datasets across multiple language ecosystems
- compare pass/fail, runtime, and token/cost metrics across agents

## Technologies

### language
- Python

### main frameworks
- `typer` for CLI commands
- `pydantic` for dataset/config/result schemas
- `docker` Python SDK for container execution
- `rich` for TTY console output
- `pytest` for tests
- `ruff` for linting and formatting
- `mypy` in strict mode for type checking
- `uv` for dependency and command execution

## Environment
- Project venv: `.venv`
- Python in project venv: `.venv/bin/python`

Notes:
- `pyproject.toml` requires Python `>=3.10`.
- `ruff` and `mypy` are expected to run through `uv run ...` even if not on global `PATH`.

### path to dependencies
- Lock file: `uv.lock`
- Project virtualenv: `.venv`
- Installed site-packages: `.venv/lib/python*/site-packages`
- `uv` cache: `.uv-cache`

### docker
- Reference image files live in `docker/universal/`.
- The universal image is intended for multi-language benchmark execution.
- `benchrail run --mode docker` uses the Python Docker SDK, not raw shell-only orchestration.
- Example default image name used in docs/tests: `benchrail-universal:latest`.
- Docker mode can inherit host env vars, install/select agent CLIs, and optionally copy auth session files into task containers.

## Commands

### install
Preferred:
```bash
uv sync --dev
```

Fallback if `uv sync` is unavailable in your environment but the repo already has `.venv`:
```bash
uv run python --version
```

### run tests
Unit tests:
```bash
make unit
```

Equivalent:
```bash
uv run pytest tests/unit/ -v
```

Validate example dataset:
```bash
uv run benchrail validate --dataset examples/multi-swe-bench-universal-smoke
```

Run example benchmark in docker mode:
```bash
uv run benchrail run \
  --dataset examples/multi-swe-bench-universal-smoke \
  --mode docker \
  --agents codex-gpt-5.4-mini-medium
```

### run lints
```bash
make lint
```

Equivalent:
```bash
uv run ruff check benchrail/ tests/
uv run mypy benchrail tests
```

### format
```bash
make format
```

Equivalent:
```bash
uv run ruff format benchrail/ tests/
uv run ruff check --fix benchrail/ tests/
```

## Project structure (tests, application, scripts etc)

```text
benchrail/
  cli.py                 # Typer entrypoint
  registry.py            # agent registry and adapter factory
  pricing.py             # token cost/credit lookup helpers
  adapters/              # agent-specific command and output parsing
  commands/              # CLI subcommands: run, validate
  dto/                   # Pydantic models for configs, manifest, results
  runner/                # orchestration, local/docker execution, logging

tests/
  unit/                  # unit tests for adapters, DTOs, runner pieces
  integration/           # reserved for broader integration coverage

docker/universal/
  Dockerfile             # reference multi-language benchmark image
  setup_universal.sh     # runtime/toolchain provisioning
  setup_agents.sh        # agent CLI provisioning
  verify.sh              # validation for universal image matrix

examples/
  multi-swe-bench-universal-smoke/
                         # example dataset with manifest + instances
```

Dataset instance layout convention:
```text
<dataset>/
  manifest.json
  <instance_id>/
    config.json
    environment/
      setup.sh
      run-selected-tests.sh
      run-gold-tests.sh
    patches/
      test.patch
      original_swe_test.patch
```

## Application Architecture/Layers

### 1. CLI layer
Files:
- `benchrail/cli.py`
- `benchrail/commands/run.py`
- `benchrail/commands/validate.py`

Responsibilities:
- parse CLI arguments
- perform basic argument validation
- dispatch to orchestration or dataset validation
- convert exceptions to exit codes

### 2. Schema/DTO layer
Files:
- `benchrail/dto/config.py`
- `benchrail/dto/manifest.py`
- `benchrail/dto/result.py`

Responsibilities:
- validate dataset format
- enforce safe path/env conventions
- model run/task/check result payloads
- aggregate run-level statistics

### 3. Registry/adapter layer
Files:
- `benchrail/registry.py`
- `benchrail/adapters/base.py`
- `benchrail/adapters/codex.py`
- `benchrail/adapters/claude_code.py`

Responsibilities:
- map manifest agent type to adapter implementation
- construct agent CLI commands
- parse agent stdout/stderr into normalized metrics
- expose auth session file locations per agent

### 4. Runner/orchestration layer
Files:
- `benchrail/runner/orchestrator.py`
- `benchrail/runner/worker.py`
- `benchrail/runner/local.py`
- `benchrail/runner/docker.py`
- `benchrail/runner/logging_util.py`

Responsibilities:
- load manifest and instance configs
- build the task queue
- manage concurrency with `ThreadPoolExecutor`
- prepare repositories and task environments
- run hooks, agent step, and check commands
- collect logs and write result artifacts

### 5. Environment/image layer
Files:
- `docker/universal/*`
- `examples/multi-swe-bench-universal-smoke/*`

Responsibilities:
- provide reproducible toolchains for benchmark tasks
- support multi-language repositories
- document canonical example datasets and container usage

## Style Guide/Coding Conventions

- Follow existing repository style; do not introduce a new architectural pattern for small changes.
- Keep modules single-purpose. This codebase is intentionally split by concern: CLI, DTO, adapters, runner.
- Use type hints everywhere. `mypy` runs in `strict = true`.
- Prefer `Path` over raw string paths in Python code.
- Use Pydantic validators for config validation instead of ad hoc parsing in command/runner code.
- Prefer deterministic behavior:
  - sort task inputs where order matters
  - keep filesystem-safe IDs
  - write outputs atomically where already established
- Keep stdout/stderr handling explicit. This repo treats logs and execution artifacts as first-class outputs.
- Reuse the adapter abstraction for new agent CLIs. Do not special-case agent parsing in worker/orchestrator.
- Preserve existing log/event naming conventions in runner code.
- Keep comments sparse and factual.
- Use double quotes and a max line length of 100, matching Ruff config.

## Testing

### technologies
- `pytest`
- `mypy`
- `ruff`

### structure
- `tests/unit/test_adapters.py`: adapter command construction and output parsing
- `tests/unit/test_dto.py`: manifest/config/result validation rules
- `tests/unit/test_pricing.py`: model price and credit calculations
- `tests/unit/test_worker.py`: worker helpers, env resolution, auth session handling, patch parsing
- `tests/unit/test_docker.py`: docker runner behavior with fakes
- `tests/unit/test_local.py`: local git/patch behavior
- `tests/integration/`: currently minimal placeholder area

### style guide
- Prefer focused unit tests over broad end-to-end tests for core helpers.
- Use `pytest.raises(...)` for validation failures.
- Use temporary directories and fake clients instead of relying on external services.
- Keep test names explicit about behavior.
- Match existing style: simple function tests, no class-based test suites.
- When adding a bug fix, add or update the narrowest test that proves the behavior.

### common components/functions
Useful code paths to reuse in tests and features:
- `Manifest.model_validate(...)`
- `InstanceConfig.model_validate(...)`
- `RunResult.aggregate(...)`
- `build_adapter(...)`
- `CodexAdapter.parse_result(...)`
- `ClaudeCodeAdapter.parse_result(...)`
- `run_benchmark(...)`
- `run_command(...)`
- `build_image(...)` / docker task runner helpers

## Solving typical tasks

### how to add a new agent type
1. Add a new adapter under `benchrail/adapters/`.
2. Subclass `BaseAdapter`.
3. Implement `_base_command(...)` and `parse_result(...)`.
4. If the CLI uses a persistent auth file, implement `auth_session_file()`.
5. Register the agent in `AGENT_REGISTRY` in `benchrail/registry.py`.
6. Add tests for command construction and output parsing.

Code example:
```python
from benchrail.adapters.base import AgentRunResult, BaseAdapter

class MyAgentAdapter(BaseAdapter):
    def _base_command(self, execution_mode: str) -> list[str]:
        return ["my-agent", "run", "--json"]

    def parse_result(
        self,
        stdout: bytes,
        stderr: bytes,
        exit_code: int,
        duration_ms: int,
    ) -> AgentRunResult:
        return AgentRunResult(
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            duration_ms=duration_ms,
        )
```

### how to add a new dataset instance
1. Create a new directory under the dataset root named exactly as `instance_id`.
2. Add `config.json`.
3. Add `environment/` scripts if setup/check execution requires them.
4. Add patch files under `patches/` if the benchmark needs them.
5. Ensure `check_commands[].name` values are unique.
6. Run validation before running the benchmark.

Code example:
```bash
uv run benchrail validate --dataset path/to/dataset
```

### how to add a new CLI command
1. Create a module under `benchrail/commands/`.
2. Define a Typer-compatible function.
3. Register it in `benchrail/cli.py`.
4. Keep argument validation in the command layer and business logic in a lower layer.

Code example:
```python
app.command("my-command")(my_command_fn)
```

### how to change config validation rules
1. Put schema rules in `benchrail/dto/config.py` or `manifest.py`.
2. Prefer `field_validator` / `model_validator` over post-hoc checks in runners.
3. Update validation tests in `tests/unit/test_dto.py`.
4. If validation affects CLI UX, confirm `validate` command output remains readable.

### how to extend result aggregation
1. Add fields to `AgentStats`, `InstanceResult`, or `RunResult` only where they are semantically correct.
2. Update `RunResult.aggregate(...)`.
3. Update CSV output in `orchestrator.py` if the new field belongs in summary exports.
4. Add tests covering partial/missing values.

### how to work on docker mode
1. Read `docker/universal/README.md` first.
2. Keep environment selection via `BENCH_ENV_*` variables.
3. Prefer extending the reference image/scripts over embedding one-off shell logic in Python.
4. Test with fake Docker clients for unit coverage, then with the smoke dataset for real behavior.

Code example:
```bash
docker build -f docker/universal/Dockerfile -t benchrail-universal:latest .
uv run benchrail run --dataset examples/multi-swe-bench-universal-smoke --mode docker
```

## Instructions

### create executing plan
Before substantial changes:
1. Identify which layer is being changed: CLI, DTO, adapter, runner, or docker environment.
2. Find the narrowest existing tests that cover adjacent behavior.
3. Decide whether the change is schema-only, runtime-only, or both.
4. Make the minimal change that keeps current abstractions intact.
5. Run targeted tests first, then broader lint/type checks if the change crosses module boundaries.

Recommended execution plan template:
1. Read affected files and adjacent tests.
2. Implement the smallest coherent change.
3. Add or update tests.
4. Run `uv run pytest ...` for the touched area.
5. Run `make lint` if public types, validation, or cross-module flow changed.

### use <libs>
Use these libraries in the roles they already own in the codebase:
- `typer`: CLI option parsing and exit handling
- `pydantic`: validation and DTO modeling
- `docker`: container build/run/exec interactions
- `rich`: console output only, not business logic
- `pytest`: tests
- `ruff`: formatting/linting
- `mypy`: strict typing gate

Library-specific guidance:
- Use `pydantic` validators for config rules.
- Use `Path` and structured DTOs instead of passing unvalidated dicts through the runner.
- Use the Docker SDK in Python runner code instead of shelling out to `docker` for core execution logic.
- Use `uv run ...` for repo commands to avoid host-environment drift.

### Avoid
- Do not bypass DTO validation by reading raw config dicts deep in the runner.
- Do not put agent-specific parsing logic into `worker.py` or `orchestrator.py`.
- Do not hardcode ad hoc environment variable aliases outside the dedicated env-resolution helpers.
- Do not introduce non-deterministic task ordering where stable sorting already exists.
- Do not mix formatting-only edits into behavior changes unless necessary.
- Do not rely on globally installed `pytest`, `ruff`, or `mypy`; use `uv run`.
- Do not add broad integration behavior to unit tests when a fake/stub is enough.
- Do not write files outside the run workspace/dataset conventions without a strong reason.
- Do not assume `docker.image` and `docker.dockerfile` can coexist; they are intentionally mutually exclusive.
- Do not let patch or dockerfile paths escape the instance directory.
