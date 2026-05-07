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
from universal_interface.workflow_runner import run_workflow

app = typer.Typer(help="Universal AI Interface CLI", no_args_is_help=True)
workflow_app = typer.Typer(help="YAML workflows from config.yaml")
app.add_typer(workflow_app, name="workflow")
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
        mode = ctx.config.ai.inference
        hint = (
            "local inference (e.g. Ollama) — set ai.inference: cloud + API keys for hosted models"
            if mode == "local"
            else "cloud inference — ensure provider API keys are set"
        )
        console.print(
            f"[bold green]Universal AI Interface[/bold green] — "
            f'[dim]"/quit" to exit · mode: [cyan]{mode}[/cyan] · {hint}[/dim]'
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


@app.command()
def health(
    data_dir: Path | None = typer.Option(
        None,
        "--data-dir",
        help="Override UAI_DATA_DIR (default: ./data)",
    ),
) -> None:
    """Run each connector's health check (tokens/env-dependent)."""

    async def _run() -> None:
        env = EnvSettings()
        if data_dir is not None:
            env.data_dir = data_dir
        ctx = await AppContext.create(env=env)
        try:
            for c in sorted(ctx.registry.all(), key=lambda x: x.name):
                h = await c.health_check()
                status = "[green]OK[/green]" if h.ok else "[red]FAIL[/red]"
                lat = f"{h.latency_ms:.0f}ms" if h.latency_ms is not None else "—"
                console.print(f"{status} [bold]{c.name}[/bold] ({lat}) — {h.message}")
        finally:
            await ctx.shutdown()

    asyncio.run(_run())


@workflow_app.command("run")
def workflow_run(
    name: str = typer.Argument(..., help="Workflow key under workflows: in config.yaml."),
    data_dir: Path | None = typer.Option(
        None,
        "--data-dir",
        help="Override UAI_DATA_DIR (default: ./data)",
    ),
) -> None:
    """Execute one workflow (same engine used by the web scheduler)."""

    async def _run() -> None:
        env = EnvSettings()
        if data_dir is not None:
            env.data_dir = data_dir
        ctx = await AppContext.create(env=env)
        try:
            text = await run_workflow(ctx, name)
            console.print(Markdown(text))
        finally:
            await ctx.shutdown()

    asyncio.run(_run())


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", "--host", help="Bind address (default: localhost only)."),
    port: int = typer.Option(8765, "--port", help="HTTP port."),
    open_browser: bool = typer.Option(False, "--open", help="Try to open the UI in your browser."),
) -> None:
    """Run a minimal web UI in your browser (same backend as ``uai chat``)."""

    import uvicorn

    url = f"http://{host}:{port}/"
    if host == "0.0.0.0":
        url = f"http://127.0.0.1:{port}/"
    console.print(f"[green]Universal AI Interface[/green] web dashboard → [bold cyan]{url}[/bold cyan]")
    console.print("[dim]Stop with Ctrl+C[/dim]")
    if open_browser:
        try:
            import webbrowser

            webbrowser.open(url)
        except Exception:
            pass
    uvicorn.run(
        "universal_interface.web:app",
        host=host,
        port=port,
        factory=False,
        log_level="info",
    )


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
