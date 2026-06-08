"""CLI command: benchrail validate"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer


def _load_json_object(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path.name} must contain a JSON object")
    return payload


def validate_cmd(
    dataset: Annotated[
        Path,
        typer.Option("--dataset", help="Path to dataset directory"),
    ] = Path("dataset"),
) -> None:
    """Validate dataset structure and all configuration files."""
    from benchrail.dto.config import InstanceConfig
    from benchrail.dto.manifest import Manifest
    from benchrail.registry import AGENT_REGISTRY

    errors: list[str] = []
    warnings: list[str] = []

    if not dataset.is_dir():
        typer.echo(f"Error: dataset path does not exist: {dataset}", err=True)
        raise typer.Exit(2)

    manifest_file = dataset / "manifest.json"
    if not manifest_file.exists():
        typer.echo("Error: manifest.json not found", err=True)
        raise typer.Exit(2)

    manifest: Manifest | None = None
    try:
        data = _load_json_object(manifest_file)
        manifest = Manifest.model_validate(data)
        typer.echo(f"  manifest.json  OK  ({len(manifest.agents)} agents)")
    except Exception as e:
        errors.append(f"manifest.json invalid: {e}")

    if manifest:
        for agent in manifest.agents:
            if agent.agent not in AGENT_REGISTRY:
                errors.append(
                    f"manifest: agent type {agent.agent!r} (id={agent.id!r}) not in AGENT_REGISTRY"
                )

    instance_count = 0
    for item in sorted(dataset.iterdir()):
        if not item.is_dir():
            continue
        config_file = item / "config.json"
        if not config_file.exists():
            continue

        instance_count += 1
        try:
            data = _load_json_object(config_file)
            config = InstanceConfig.model_validate(data)
        except Exception as e:
            errors.append(f"{item.name}/config.json invalid: {e}")
            continue

        if config.instance_id != item.name:
            errors.append(
                f"{item.name}: instance_id {config.instance_id!r} does not match directory name"
            )

        try:
            config.resolve_patch_paths(item)
        except ValueError as e:
            errors.append(f"{item.name}: {e}")
        try:
            config.docker.resolve_dockerfile_path(item)
        except ValueError as e:
            errors.append(f"{item.name}: {e}")

        typer.echo(f"  {item.name}/config.json  OK")

    if instance_count == 0:
        warnings.append("No instances found in dataset")

    typer.echo(f"\nTotal: {instance_count} instance(s)")

    if warnings:
        typer.echo("")
        for w in warnings:
            typer.echo(f"  WARNING: {w}")
    if errors:
        typer.echo("")
        for err in errors:
            typer.echo(f"  ERROR: {err}", err=True)
        raise typer.Exit(2)

    typer.echo("\nDataset is valid.")
