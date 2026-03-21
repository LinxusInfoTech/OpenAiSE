# aise/cli/app.py
"""Typer root CLI application.

This module provides the main CLI entry point for the AiSE system,
registering all command groups and providing version information.

Example usage:
    $ aise version
    $ aise ask "Why is my pod crashing?"
    $ aise learn list
    $ aise learn enable aws
    $ aise init
"""

import typer
import structlog

logger = structlog.get_logger(__name__)

# Create main Typer app
app = typer.Typer(
    name="aise",
    help="AI Support Engineer System",
    no_args_is_help=True
)


@app.command()
def version():
    """Show version information."""
    typer.echo("AiSE (AI Support Engineer System) v0.1.0")


# Import and register command groups
from aise.cli.commands.ask import ask_app, main as ask_main
from aise.cli.commands.learn import learn_app
from aise.cli.commands.init import init_app
from aise.cli.commands.config import config_app
from aise.cli.commands.mode import mode_app
from aise.cli.commands.ticket import ticket_app
from aise.cli.commands.start import start_app

# Register `aise ask "question"` as a top-level command
app.command(name="ask")(ask_main)

app.add_typer(learn_app, name="learn")
app.add_typer(init_app, name="init")
app.add_typer(config_app, name="config")
app.add_typer(mode_app, name="mode")
app.add_typer(ticket_app, name="ticket")
app.add_typer(start_app, name="start")


if __name__ == "__main__":
    app()
