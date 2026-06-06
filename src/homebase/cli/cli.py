from __future__ import annotations

import os
from pathlib import Path
import typer
from rich.console import Console
from typing_extensions import Annotated


class Config:
    """Runtime configuration shared across all commands."""

    no_color: bool = True
    console: Console = Console(no_color=True)


cfg = Config()

app = typer.Typer(
    name="homebase",
    help="Homebase: homelab documentation and inventory tool.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)


_DEFAULT_HOST = os.environ.get("HOMEBASE_HOST", "0.0.0.0")
_DEFAULT_PORT = int(os.environ.get("HOMEBASE_PORT", "8000"))
_DEFAULT_SCHEMA = os.environ.get("HOMEBASE_SCHEMA_PATH", "schema.yaml")
_DEFAULT_DB = os.environ.get("HOMEBASE_DB_PATH", "data/db.json")


@app.command()
def list(
    ctx: typer.Context,
) -> None:
    """List all entities in the schema."""
    from homebase.core.config import schema

    for entity in schema.entities.values():
        cfg.console.print(f"- [bold]{entity.name}[/bold]")


@app.command()
def serve(
    host: Annotated[
        str, typer.Option("--host", "-h", help="Bind host.")
    ] = _DEFAULT_HOST,
    port: Annotated[
        int, typer.Option("--port", "-p", help="Bind port.")
    ] = _DEFAULT_PORT,
    schema: Annotated[
        Path, typer.Option("--schema", "-s", help="Path to schema.yaml.")
    ] = Path(_DEFAULT_SCHEMA),
    db: Annotated[
        Path, typer.Option("--db", "-d", help="Path to the TinyDB JSON file.")
    ] = Path(_DEFAULT_DB),
    reload: Annotated[
        bool, typer.Option("--reload", help="Enable hot-reload (dev).")
    ] = False,
) -> None:
    """Start the homebase web server."""
    import uvicorn

    # Set env vars before the server module is imported so core/config.py picks
    # them up (it reads env at module level).
    os.environ["HOMEBASE_SCHEMA_PATH"] = str(schema)
    os.environ["HOMEBASE_DB_PATH"] = str(db)
    os.environ["HOMEBASE_HOST"] = host
    os.environ["HOMEBASE_PORT"] = str(port)

    cfg.console.print(
        f"[bold]homebase[/bold] serving on [cyan]http://{host}:{port}[/cyan]  "
        f"(schema: [dim]{schema}[/dim])"
    )

    uvicorn.run(
        "homebase.server.api:app",
        host=host,
        port=port,
        reload=reload,
    )


def main() -> None:
    app()
