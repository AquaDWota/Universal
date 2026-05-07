from __future__ import annotations

import asyncio
from pathlib import Path

import typer
from rich.console import Console
from rich.markdown import Markdown
from rich.prompt import Prompt

from universal_interface.app_context import AppContext
from universal_interface.config import EnvSettings, default_config_path, write_default_config
from universal_interface.orchestrator import handle_turn

app = typer.Typer(help="Universal AI Interface CLI", no_args_is_help=True)
console = Console()


@app.command()
def init_config(
    force: bool = typer.Option(False, "--force", "-f", help="Overwrite existing config.yaml."),
) -> None:
    """Write a starter config.yaml next to your cwd (or UAI_CONFIG_PATH)."""
    env = EnvSettings()
    path = default_config_path(env)
    if path.exists() and not force:
        console.print(f"[yellow]Already exists:[/yellow] {path} (use --force)")
        raise typer.Exit(code=1)
    write_default_config(path)
    console.print(f"[green]Wrote[/green] {path}")


@app.command()
def chat(
    data_dir: Path | None = typer.Option(
        None,
        "--data-dir",
        help="Override UAI_DATA_DIR (default: ./data)",
    ),
) -> None:
    """Interactive terminal chat (Phase 1 core loop)."""

    async def _run() -> None:
        env = EnvSettings()
        if data_dir is not None:
            env.data_dir = data_dir
        ctx = await AppContext.create(env=env)
        console.print(
            "[bold green]Universal AI Interface[/bold green] — "
            "[dim]\"/quit\" to exit · set OPENAI_API_KEY or ANTHROPIC_API_KEY for full routing[/dim]"
        )
        try:
            while True:
                user = Prompt.ask("\n[bold]>[/bold]").strip()
                if user.lower() in {"/quit", "quit", "exit"}:
                    break
                if not user:
                    continue
                reply = await handle_turn(ctx, user)
                console.print(Markdown(reply))
        finally:
            await ctx.shutdown()

    asyncio.run(_run())


@app.command("connectors")
def list_connectors() -> None:
    """List registered connectors and capabilities."""

    async def _run() -> None:
        ctx = await AppContext.create()
        try:
            for c in ctx.registry.all():
                console.print(f"[bold]{c.name}[/bold] ({c.category}) — {c.description}")
                for cap in c.capabilities:
                    flag = " ⚠ confirm" if cap.requires_confirmation else ""
                    console.print(f"  • [cyan]{cap.action_id}[/cyan]: {cap.description}{flag}")
        finally:
            await ctx.shutdown()

    asyncio.run(_run())


def main() -> None:
    app()


if __name__ == "__main__":
    main()
