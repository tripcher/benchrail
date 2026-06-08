"""CLI entry point: registers all subcommands."""

import typer

from benchrail.commands.run import run_cmd
from benchrail.commands.validate import validate_cmd
from benchrail.commands.version import version_cmd

app = typer.Typer(
    name="benchrail",
    help="Reproducible benchmark harness for coding agents.",
    add_completion=False,
    no_args_is_help=True,
)

app.command("run")(run_cmd)
app.command("validate")(validate_cmd)
app.command("version")(version_cmd)


if __name__ == "__main__":
    app()
