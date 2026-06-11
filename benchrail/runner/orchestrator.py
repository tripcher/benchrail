"""Orchestrator: reads dataset, builds task queue, runs worker pool."""

from __future__ import annotations

import csv
import io
import json
import os
import re
import signal
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from types import FrameType

from benchrail.dto.config import DatasetConfig, InstanceConfig, merge_dataset_config
from benchrail.dto.manifest import AgentEntry, Manifest
from benchrail.dto.result import InstanceResult, RunResult
from benchrail.registry import AGENT_REGISTRY
from benchrail.runner.logging_util import ConsoleOutput, RunnerLogger
from benchrail.runner.worker import TaskSpec, run_task

_RUN_ID_RE = re.compile(r"^[a-zA-Z0-9._-]+$")


class ConfigError(Exception):
    pass


def _load_json_object(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ConfigError(f"{path} must contain a JSON object")
    return payload


def _generate_run_id() -> str:
    return datetime.now(timezone.utc).strftime("run-%Y%m%d-%H%M%S")


def _validate_run_id(run_id: str) -> None:
    if not _RUN_ID_RE.match(run_id):
        raise ConfigError(f"run_id {run_id!r} is not filesystem-safe (allowed: [a-zA-Z0-9._-])")


def _load_manifest(dataset_path: Path) -> Manifest:
    manifest_file = dataset_path / "manifest.json"
    if not manifest_file.exists():
        raise ConfigError(f"manifest.json not found in {dataset_path}")
    try:
        data = _load_json_object(manifest_file)
        return Manifest.model_validate(data)
    except Exception as e:
        raise ConfigError(f"Invalid manifest.json: {e}") from e


def _load_dataset_config(dataset_path: Path) -> DatasetConfig | None:
    config_file = dataset_path / "config.json"
    if not config_file.exists():
        return None
    try:
        data = _load_json_object(config_file)
        return DatasetConfig.model_validate(data)
    except Exception as e:
        raise ConfigError(f"Invalid dataset config.json: {e}") from e


def _discover_instances(dataset_path: Path) -> dict[str, InstanceConfig]:
    """Discover all instances in dataset and return {instance_id: InstanceConfig}."""
    instances: dict[str, InstanceConfig] = {}
    dataset_config = _load_dataset_config(dataset_path)
    for item in sorted(dataset_path.iterdir()):
        if not item.is_dir():
            continue
        config_file = item / "config.json"
        if not config_file.exists():
            continue
        try:
            instance_data = _load_json_object(config_file)
            merged_data = merge_dataset_config(dataset_config, instance_data)
            config = InstanceConfig.model_validate(merged_data)
            config.docker.resolve_dockerfile_path(item, dataset_path)
        except Exception as e:
            raise ConfigError(f"Invalid config.json in {item.name}: {e}") from e

        if config.instance_id != item.name:
            raise ConfigError(
                f"instance_id {config.instance_id!r} in config.json does not match"
                f" directory name {item.name!r}"
            )
        instances[config.instance_id] = config
    return instances


def _build_task_queue(
    instances: dict[str, InstanceConfig],
    manifest: Manifest,
    filter_agents: list[str] | None,
    filter_instances: list[str] | None,
    dataset_path: Path,
) -> list[tuple[str, AgentEntry, InstanceConfig]]:
    """Return sorted list of (instance_id, agent_entry, instance_config)."""

    # Validate agent filter
    agent_ids = {a.id for a in manifest.agents}
    if filter_agents:
        unknown = set(filter_agents) - agent_ids
        if unknown:
            raise ConfigError(f"Unknown agent ids: {', '.join(sorted(unknown))}")
        selected_agents = [a for a in manifest.agents if a.id in set(filter_agents)]
    else:
        selected_agents = list(manifest.agents)

    # Validate agent types in registry
    for agent in selected_agents:
        if agent.agent not in AGENT_REGISTRY:
            raise ConfigError(
                f"Agent type {agent.agent!r} (id={agent.id!r}) not found in AGENT_REGISTRY"
            )

    # Validate instance filter
    instance_ids = set(instances.keys())
    if filter_instances:
        unknown = set(filter_instances) - instance_ids
        if unknown:
            raise ConfigError(f"Unknown instance ids: {', '.join(sorted(unknown))}")
        selected_instances = sorted(iid for iid in filter_instances if iid in instance_ids)
    else:
        selected_instances = sorted(instance_ids)

    # Validate patch paths for all selected instances
    for iid in selected_instances:
        config = instances[iid]
        instance_dir = dataset_path / iid
        try:
            config.resolve_patch_paths(instance_dir)
        except ValueError as e:
            raise ConfigError(f"Instance {iid}: {e}") from e
        try:
            config.resolve_expected_migration_json_path(instance_dir)
        except ValueError as e:
            raise ConfigError(f"Instance {iid}: {e}") from e
        try:
            config.docker.resolve_dockerfile_path(instance_dir, dataset_path)
        except ValueError as e:
            raise ConfigError(f"Instance {iid}: {e}") from e

    # Sort agents by id for deterministic order
    selected_agents.sort(key=lambda a: a.id)

    # Build cartesian product: for each instance, for each agent
    queue = []
    for iid in selected_instances:
        for agent in selected_agents:
            queue.append((iid, agent, instances[iid]))

    if not queue:
        raise ConfigError("No tasks to run after applying filters")

    return queue


def _write_csv_atomic(results: list[InstanceResult], path: Path) -> None:
    """Write CSV summary of all instance results."""
    if not results:
        return

    # Collect all check names (preserving first-seen order)
    check_names: list[str] = []
    seen: set[str] = set()
    for r in results:
        for c in r.checks:
            if c.name not in seen:
                check_names.append(c.name)
                seen.add(c.name)

    fieldnames = [
        "schema_version",
        "instance_id",
        "agent",
        "agent_session_id",
        "repo",
        "base_commit",
        "status",
        "duration_seconds",
        "agent_stats_duration_ms",
        "agent_stats_turns",
        "agent_stats_input_tokens",
        "agent_stats_output_tokens",
        "agent_stats_cache_read_tokens",
        "agent_stats_cache_creation_tokens",
        "agent_stats_reasoning_tokens",
        "agent_stats_cost_usd",
        "agent_stats_cost_credits",
    ]
    for name in check_names:
        fieldnames.append(f"checks_{name}_status")
        fieldnames.append(f"checks_{name}_duration_seconds")

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fieldnames)
    writer.writeheader()

    for r in results:
        checks_by_name = {c.name: c for c in r.checks}
        row: dict[str, str | int | float | None] = {
            "schema_version": r.schema_version,
            "instance_id": r.instance_id,
            "agent": r.agent,
            "agent_session_id": r.agent_session_id,
            "repo": r.repo,
            "base_commit": r.base_commit,
            "status": r.status,
            "duration_seconds": r.duration_seconds,
            "agent_stats_duration_ms": r.agent_stats.duration_ms,
            "agent_stats_turns": r.agent_stats.turns,
            "agent_stats_input_tokens": r.agent_stats.input_tokens,
            "agent_stats_output_tokens": r.agent_stats.output_tokens,
            "agent_stats_cache_read_tokens": r.agent_stats.cache_read_tokens,
            "agent_stats_cache_creation_tokens": r.agent_stats.cache_creation_tokens,
            "agent_stats_reasoning_tokens": r.agent_stats.reasoning_tokens,
            "agent_stats_cost_usd": r.agent_stats.cost_usd,
            "agent_stats_cost_credits": r.agent_stats.cost_credits,
        }
        for name in check_names:
            check_result = checks_by_name.get(name)
            row[f"checks_{name}_status"] = check_result.status if check_result else ""
            row[f"checks_{name}_duration_seconds"] = (
                check_result.duration_seconds if check_result else ""
            )
        writer.writerow(row)

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(buf.getvalue(), encoding="utf-8")
    tmp.rename(path)


def _write_run_result_atomic(run_result: RunResult, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(run_result.model_dump_json(indent=2), encoding="utf-8")
    tmp.rename(path)


def run_benchmark(
    dataset_path: Path,
    workspace: Path,
    mode: str,
    run_id: str | None,
    filter_agents: list[str] | None,
    filter_instances: list[str] | None,
    output: Path | None,
    logs: Path | None,
    max_workers: int | None,
    auth_session: bool = False,
) -> tuple[RunResult, int]:
    """Main entry point. Returns (RunResult, exit_code)."""

    # Validate dataset path
    if not dataset_path.is_dir():
        raise ConfigError(f"Dataset path does not exist: {dataset_path}")

    # Determine run_id
    if run_id:
        _validate_run_id(run_id)
    else:
        run_id = _generate_run_id()

    # Check workspace collision
    workspace.mkdir(parents=True, exist_ok=True)
    run_workspace = workspace / run_id
    if run_workspace.exists():
        raise ConfigError(
            f"Workspace directory already exists: {run_workspace}\n"
            "Use a different --run_id or remove it manually."
        )

    # Check output collision
    if output:
        output.mkdir(parents=True, exist_ok=True)
        run_output = output / run_id
        if run_output.exists():
            raise ConfigError(
                f"Output directory already exists: {run_output}\n"
                "Use a different --run_id or remove it manually."
            )

    logs_root = logs or workspace
    logs_root.mkdir(parents=True, exist_ok=True)
    run_logs = logs_root / run_id
    if run_logs.exists():
        raise ConfigError(
            f"Logs directory already exists: {run_logs}\n"
            "Use a different --run_id or remove it manually."
        )

    # Load dataset
    manifest = _load_manifest(dataset_path)
    instances = _discover_instances(dataset_path)

    # Build task queue
    task_queue = _build_task_queue(
        instances, manifest, filter_agents, filter_instances, dataset_path
    )

    n_tasks = len(task_queue)
    effective_workers = min(max_workers or os.cpu_count() or 1, n_tasks)

    # Setup run logger and console
    run_workspace.mkdir(parents=True, exist_ok=True)
    run_logs.mkdir(parents=True, exist_ok=True)
    run_logger = RunnerLogger(run_logs / "runner.log")
    console = ConsoleOutput()

    run_logger.info(
        "RUN_START",
        run_id=run_id,
        mode=mode,
        dataset=str(dataset_path),
        tasks=n_tasks,
        workers=effective_workers,
    )
    console.run_start(run_id, mode, str(dataset_path), n_tasks, effective_workers)

    # Stop flag for graceful shutdown
    stop_flag = threading.Event()
    run_status = "completed"
    start_time = time.monotonic()

    def _handle_signal(sig: int, frame: FrameType | None) -> None:
        nonlocal run_status
        del frame
        run_status = "aborted"
        stop_flag.set()
        console.print(f"\n[signal] Run aborted (signal {sig}), finishing current tasks...")

    prev_sigint = signal.signal(signal.SIGINT, _handle_signal)
    prev_sigterm = signal.signal(signal.SIGTERM, _handle_signal)

    instance_results: list[InstanceResult] = []

    try:
        with ThreadPoolExecutor(max_workers=effective_workers) as pool:
            futures: dict[Future[InstanceResult], TaskSpec] = {}

            for iid, agent_entry, instance_config in task_queue:
                if stop_flag.is_set():
                    break
                spec = TaskSpec(
                    instance_id=iid,
                    agent_entry=agent_entry,
                    instance_config=instance_config,
                    instance_dir=dataset_path / iid,
                    workspace_root=workspace,
                    output_root=output,
                    logs_root=logs_root,
                    run_id=run_id,
                    mode=mode,
                    auth_session=auth_session,
                    stop_flag=stop_flag,
                )
                future = pool.submit(run_task, spec, run_logger, console)
                futures[future] = spec

            for future in as_completed(futures):
                spec = futures[future]
                try:
                    result = future.result()
                    instance_results.append(result)
                except Exception as exc:
                    run_logger.error(
                        "WORKER_CRASH",
                        instance=spec.instance_id,
                        agent=spec.agent_entry.id,
                        error=str(exc)[:500],
                    )
                    run_status = "failed"

    except Exception as exc:
        run_logger.error("ORCHESTRATOR_ERROR", error=str(exc)[:500])
        run_status = "failed"
    finally:
        signal.signal(signal.SIGINT, prev_sigint)
        signal.signal(signal.SIGTERM, prev_sigterm)

    duration_seconds = time.monotonic() - start_time

    # Aggregate run result
    run_result = RunResult.aggregate(
        run_id=run_id,
        mode=mode,
        dataset_path=str(dataset_path),
        status=run_status,
        duration_seconds=duration_seconds,
        instance_results=instance_results,
    )

    # Write aggregated artifacts
    output_root = output or workspace
    run_result_path = output_root / run_id / "result.json"
    csv_path = output_root / run_id / "result.csv"

    try:
        _write_run_result_atomic(run_result, run_result_path)
        _write_csv_atomic(instance_results, csv_path)
    except Exception as exc:
        run_logger.error("RESULT_WRITE_FAILED", error=str(exc)[:500])
        run_result = run_result.model_copy(update={"status": "failed"})
        run_status = "failed"

    run_logger.info(
        "RUN_END",
        status=run_result.status,
        passed=run_result.passed,
        failed=run_result.failed,
        total=run_result.total,
        duration_seconds=round(duration_seconds, 1),
    )
    run_logger.close()

    # Console summary
    console.run_end(
        status=run_result.status,
        passed=run_result.passed,
        failed=run_result.failed,
        total=run_result.total,
        duration=duration_seconds,
        cost_usd=run_result.total_cost_usd,
        cost_credits=run_result.total_cost_credits,
        input_tokens=run_result.total_input_tokens,
        output_tokens=run_result.total_output_tokens,
    )

    failed_tasks = [
        (r.instance_id, r.agent, "fail") for r in instance_results if r.status == "fail"
    ]
    console.print_summary(
        passed=run_result.passed,
        failed=run_result.failed,
        total=run_result.total,
        failed_tasks=failed_tasks,
        cost_usd=run_result.total_cost_usd,
        cost_credits=run_result.total_cost_credits,
        input_tokens=run_result.total_input_tokens,
        output_tokens=run_result.total_output_tokens,
        cache_read_tokens=run_result.total_cache_read_tokens,
        total_time=duration_seconds,
        agent_time=run_result.total_agent_duration_ms,
    )

    # Determine exit code
    if run_result.status == "completed":
        exit_code = 0
    elif run_result.status == "aborted":
        exit_code = 130
    else:
        exit_code = 1

    return run_result, exit_code
