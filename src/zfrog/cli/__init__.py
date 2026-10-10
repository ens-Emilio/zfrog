"""CLI package entrypoint — Typer app and command registration."""

import typer

from zfrog.cli._shared import console

app = typer.Typer(
    name="zfrog",
    help="Design reference engine: capture, organize and adapt web design references.",
    no_args_is_help=True,
)

# Import command modules for side-effects (they register @app.command / add_typer).
from zfrog.cli.commands import (  # noqa: E402
    capture,  # noqa: F401
    catalog,  # noqa: F401
    jobs,  # noqa: F401
    system,  # noqa: F401
    workspaces,  # noqa: F401
)

__all__ = ["app", "console"]
