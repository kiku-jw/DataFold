"""Main CLI entry point for DataFold Agent."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import click
from rich.console import Console

from datafold import __version__
from datafold.config import (
    find_config_file,
    generate_example_config,
    load_config,
    mask_secrets,
    resolve_config_env_vars,
)

console = Console()
error_console = Console(stderr=True)


def setup_logging(level: str, format: str = "text") -> None:
    """Configure logging."""
    log_level = getattr(logging, level.upper(), logging.INFO)

    if format == "json":
        import json

        class JsonFormatter(logging.Formatter):
            def format(self, record: logging.LogRecord) -> str:
                return json.dumps(
                    {
                        "timestamp": self.formatTime(record),
                        "level": record.levelname,
                        "logger": record.name,
                        "message": record.getMessage(),
                    }
                )

        handler = logging.StreamHandler()
        handler.setFormatter(JsonFormatter())
    else:
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
        )

    logging.root.handlers = [handler]
    logging.root.setLevel(log_level)


@click.group()
@click.version_option(version=__version__, prog_name="datafold")
@click.option(
    "--config",
    "-c",
    type=click.Path(exists=False),
    help="Path to config file",
)
@click.option(
    "--verbose",
    "-v",
    is_flag=True,
    help="Enable verbose output",
)
@click.option(
    "--quiet",
    "-q",
    is_flag=True,
    help="Suppress non-essential output",
)
@click.option(
    "--json",
    "json_output",
    is_flag=True,
    help="Output in JSON format",
)
@click.pass_context
def cli(
    ctx: click.Context,
    config: str | None,
    verbose: bool,
    quiet: bool,
    json_output: bool,
) -> None:
    """DataFold Agent - Automated data quality & drift detection."""
    ctx.ensure_object(dict)
    ctx.obj["config_path"] = Path(config) if config else None
    ctx.obj["verbose"] = verbose
    ctx.obj["quiet"] = quiet
    ctx.obj["json_output"] = json_output


@cli.command()
@click.option(
    "--path",
    "-p",
    type=click.Path(),
    default="./datafold.yaml",
    help="Path to create config file",
)
def init(path: str) -> None:
    """Initialize a new DataFold configuration file."""
    config_path = Path(path)

    if config_path.exists():
        error_console.print(f"[red]Error:[/red] Config file already exists: {config_path}")
        sys.exit(1)

    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(generate_example_config())

    console.print(f"[green]Created config file:[/green] {config_path}")
    console.print("\nNext steps:")
    console.print("  1. Edit the config file with your data sources")
    console.print("  2. Set environment variables for secrets")
    console.print("  3. Run: datafold validate")
    console.print("  4. Run: datafold check")


@cli.command()
@click.pass_context
def validate(ctx: click.Context) -> None:
    """Validate configuration file."""
    config_path = ctx.obj["config_path"] or find_config_file()

    if not config_path:
        error_console.print("[red]Error:[/red] No config file found")
        error_console.print("Run 'datafold init' to create one")
        sys.exit(1)

    try:
        config = load_config(config_path)
        resolve_config_env_vars(config)  # Validate env vars resolve

        console.print(f"[green]Config valid:[/green] {config_path}")
        console.print(f"  Version: {config.version}")
        console.print(f"  Sources: {len(config.sources)}")
        console.print(f"  Webhooks: {len(config.alerting.webhooks)}")
        console.print(f"  Storage: {config.storage.backend}")

    except FileNotFoundError:
        error_console.print(f"[red]Error:[/red] Config file not found: {config_path}")
        sys.exit(1)
    except ValueError as e:
        error_console.print(f"[red]Validation error:[/red] {e}")
        sys.exit(1)
    except Exception as e:
        error_console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)


@cli.command("render-config")
@click.pass_context
def render_config(ctx: click.Context) -> None:
    """Show resolved configuration with masked secrets."""
    config_path = ctx.obj["config_path"] or find_config_file()

    if not config_path:
        error_console.print("[red]Error:[/red] No config file found")
        sys.exit(1)

    try:
        config = load_config(config_path)
        resolved = resolve_config_env_vars(config)

        console.print("[bold]Resolved Configuration[/bold]\n")

        console.print("[bold]Agent:[/bold]")
        console.print(f"  ID: {resolved.agent.id}")
        console.print(f"  Log Level: {resolved.agent.log_level}")

        console.print("\n[bold]Storage:[/bold]")
        console.print(f"  Backend: {resolved.storage.backend}")
        if resolved.storage.backend == "sqlite":
            console.print(f"  Path: {resolved.storage.path}")
        else:
            console.print(f"  Connection: {mask_secrets(resolved.storage.connection or '')}")

        console.print("\n[bold]Sources:[/bold]")
        for source in resolved.sources:
            status = "[green]enabled[/green]" if source.enabled else "[red]disabled[/red]"
            console.print(f"  - {source.name} ({source.dialect}) {status}")
            console.print(f"    Connection: {mask_secrets(source.connection)}")
            console.print(f"    Schedule: {source.schedule}")

        console.print("\n[bold]Webhooks:[/bold]")
        for webhook in resolved.alerting.webhooks:
            console.print(f"  - {webhook.name}")
            console.print(f"    URL: {mask_secrets(webhook.url)}")
            console.print(f"    Events: {', '.join(webhook.events)}")

    except Exception as e:
        error_console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)


@cli.command()
@click.option("--source", "-s", help="Check specific source only")
@click.option("--force", "-f", is_flag=True, help="Ignore schedule, check all sources")
@click.option("--dry-run", is_flag=True, help="Don't send alerts, just show what would happen")
@click.pass_context
def check(ctx: click.Context, source: str | None, force: bool, dry_run: bool) -> None:
    """Run checks on data sources."""
    from datafold.cli.commands import run_check

    config_path = ctx.obj["config_path"] or find_config_file()
    verbose = ctx.obj["verbose"]
    json_output = ctx.obj["json_output"]

    if not config_path:
        error_console.print("[red]Error:[/red] No config file found")
        sys.exit(1)

    exit_code = run_check(
        config_path=config_path,
        source_filter=source,
        force=force,
        dry_run=dry_run,
        verbose=verbose,
        json_output=json_output,
    )

    sys.exit(exit_code)


@cli.command()
@click.option("--health-port", type=int, help="Port for health endpoint")
@click.pass_context
def run(ctx: click.Context, health_port: int | None) -> None:
    """Run agent in daemon mode with internal scheduler."""
    from datafold.cli.commands import run_daemon

    config_path = ctx.obj["config_path"] or find_config_file()

    if not config_path:
        error_console.print("[red]Error:[/red] No config file found")
        sys.exit(1)

    run_daemon(config_path=config_path, health_port=health_port)


@cli.command()
@click.pass_context
def status(ctx: click.Context) -> None:
    """Show current status of all sources."""
    from datafold.cli.commands import show_status

    config_path = ctx.obj["config_path"] or find_config_file()

    if not config_path:
        error_console.print("[red]Error:[/red] No config file found")
        sys.exit(1)

    show_status(config_path=config_path, json_output=ctx.obj["json_output"])


@cli.command()
@click.argument("source_name")
@click.option("--limit", "-n", default=10, help="Number of snapshots to show")
@click.pass_context
def history(ctx: click.Context, source_name: str, limit: int) -> None:
    """Show snapshot history for a source."""
    from datafold.cli.commands import show_history

    config_path = ctx.obj["config_path"] or find_config_file()

    if not config_path:
        error_console.print("[red]Error:[/red] No config file found")
        sys.exit(1)

    show_history(
        config_path=config_path,
        source_name=source_name,
        limit=limit,
        json_output=ctx.obj["json_output"],
    )


@cli.command()
@click.option("--source", "-s", required=True, help="Source name to explain")
@click.pass_context
def explain(ctx: click.Context, source: str) -> None:
    """Explain baseline and detection thresholds for a source."""
    from datafold.cli.commands import explain_source

    config_path = ctx.obj["config_path"] or find_config_file()

    if not config_path:
        error_console.print("[red]Error:[/red] No config file found")
        sys.exit(1)

    explain_source(
        config_path=config_path,
        source_name=source,
        json_output=ctx.obj["json_output"],
    )


@cli.command("test-webhook")
@click.option("--target", "-t", help="Specific webhook target to test")
@click.pass_context
def test_webhook(ctx: click.Context, target: str | None) -> None:
    """Send a test webhook payload."""
    from datafold.cli.commands import test_webhook_delivery

    config_path = ctx.obj["config_path"] or find_config_file()

    if not config_path:
        error_console.print("[red]Error:[/red] No config file found")
        sys.exit(1)

    test_webhook_delivery(config_path=config_path, target_name=target)


@cli.command()
@click.option("--dry-run", is_flag=True, help="Show what would be deleted")
@click.pass_context
def purge(ctx: click.Context, dry_run: bool) -> None:
    """Clean up old snapshots according to retention policy."""
    from datafold.cli.commands import run_purge

    config_path = ctx.obj["config_path"] or find_config_file()

    if not config_path:
        error_console.print("[red]Error:[/red] No config file found")
        sys.exit(1)

    run_purge(config_path=config_path, dry_run=dry_run)


@cli.command()
@click.pass_context
def migrate(ctx: click.Context) -> None:
    """Apply storage migrations."""
    from datafold.cli.commands import run_migrate

    config_path = ctx.obj["config_path"] or find_config_file()

    if not config_path:
        error_console.print("[red]Error:[/red] No config file found")
        sys.exit(1)

    run_migrate(config_path=config_path)


if __name__ == "__main__":
    cli()
