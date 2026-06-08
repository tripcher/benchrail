"""CLI command: benchrail run"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer


def run_cmd(
    dataset: Annotated[
        Path,
        typer.Option("--dataset", help="Path to dataset directory"),
    ] = Path("dataset"),
    mode: Annotated[
        str,
        typer.Option("--mode", help="Execution mode: local|docker"),
    ] = "local",
    workspace: Annotated[
        Path,
        typer.Option("--workspace", help="Workspace root directory (default: current dir)"),
    ] = Path("."),
    agents: Annotated[
        str | None,
        typer.Option("--agents", help="Comma-separated agent ids to run"),
    ] = None,
    instance_ids: Annotated[
        str | None,
        typer.Option("--instance_ids", help="Comma-separated instance ids to run"),
    ] = None,
    output: Annotated[
        Path | None,
        typer.Option("--output", help="Output directory for result files"),
    ] = None,
    logs: Annotated[
        Path | None,
        typer.Option("--logs", help="Directory for runner logs and step stdout/stderr files"),
    ] = None,
    run_id: Annotated[
        str | None,
        typer.Option("--run_id", help="Run identifier (auto-generated if omitted)"),
    ] = None,
    max_workers: Annotated[
        int | None,
        typer.Option("--workers", help="Maximum parallel workers"),
    ] = None,
    auth_session: Annotated[
        bool,
        typer.Option(
            "--auth-session",
            help="In docker mode, copy the local auth session file into the task container",
        ),
    ] = False,
) -> None:
    """Run benchmark on a dataset and evaluate results."""
    from benchrail.runner.orchestrator import ConfigError, run_benchmark

    if mode not in ("local", "docker"):
        typer.echo(f"Error: --mode must be 'local' or 'docker', got {mode!r}", err=True)
        raise typer.Exit(2)

    if not dataset.is_dir():
        typer.echo(f"Error: --dataset does not point to a directory: {dataset}", err=True)
        raise typer.Exit(2)

    if not (dataset / "manifest.json").exists():
        typer.echo(f"Error: manifest.json not found in {dataset}", err=True)
        raise typer.Exit(2)

    if max_workers is not None and max_workers <= 0:
        typer.echo("Error: --workers must be a positive integer", err=True)
        raise typer.Exit(2)

    filter_agents = [a.strip() for a in agents.split(",")] if agents else None
    filter_instances = [i.strip() for i in instance_ids.split(",")] if instance_ids else None
    try:
        _, exit_code = run_benchmark(
            dataset_path=dataset.resolve(),
            workspace=workspace.resolve(),
            mode=mode,
            run_id=run_id,
            filter_agents=filter_agents,
            filter_instances=filter_instances,
            output=output.resolve() if output else None,
            logs=logs.resolve() if logs else None,
            max_workers=max_workers,
            auth_session=auth_session,
        )
    except ConfigError as e:
        typer.echo(f"Configuration error: {e}", err=True)
        raise typer.Exit(2) from None
    except Exception as e:
        typer.echo(f"Fatal error: {e}", err=True)
        raise typer.Exit(1) from None

    raise typer.Exit(exit_code)
