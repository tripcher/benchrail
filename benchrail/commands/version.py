"""CLI command for printing the benchrail version."""

import typer

from benchrail import __version__


def version_cmd() -> None:
    """Print the installed benchrail version."""
    typer.echo(__version__)
