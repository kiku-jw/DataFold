"""CLI command implementations."""

from __future__ import annotations

import json
import logging
import signal
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from croniter import croniter
from rich.console import Console
from rich.table import Table

from datafold.alerting import AlertingPipeline
from datafold.config import DataFoldConfig, load_config, resolve_config_env_vars
from datafold.connectors import SQLConnector
from datafold.detection import DetectionEngine
from datafold.models import DecisionStatus, EventType, WebhookPayload
from datafold.storage import SQLiteStateStore

console = Console()
error_console = Console(stderr=True)
logger = logging.getLogger(__name__)


def get_storage(config_path: Path) -> tuple[SQLiteStateStore, DataFoldConfig]:
    """Initialize storage from config."""
    config = load_config(config_path)
    resolved = resolve_config_env_vars(config)

    if resolved.storage.backend == "sqlite":
        store = SQLiteStateStore(resolved.storage.path)
    else:
        raise ValueError(f"Unsupported storage backend: {resolved.storage.backend}")

    store.init()
    return store, resolved


def run_check(
    config_path: Path,
    source_filter: str | None = None,
    force: bool = False,
    dry_run: bool = False,
    verbose: bool = False,
    json_output: bool = False,
) -> int:
    """Run checks on data sources. Returns exit code (0=ok, 1=error, 2=anomaly)."""
    from datafold.cli.main import setup_logging

    try:
        store, config = get_storage(config_path)
        setup_logging(config.agent.log_level if verbose else "warning")

        connector = SQLConnector()
        engine = DetectionEngine(config.baseline)
        pipeline = AlertingPipeline(
            config=config.alerting,
            store=store,
            agent_id=config.agent.id,
            dry_run=dry_run,
        )

        sources = config.sources
        if source_filter:
            sources = [s for s in sources if s.name == source_filter]
            if not sources:
                error_console.print(f"[red]Error:[/red] Source not found: {source_filter}")
                return 1

        now = datetime.now(timezone.utc)
        results = []
        has_anomaly = False

        for source in sources:
            if not source.enabled:
                continue

            if not force and not _is_due(source.schedule, store, source.name, now):
                if verbose:
                    console.print(f"[dim]Skipping {source.name}: not due yet[/dim]")
                continue

            snapshot = connector.collect_with_error_handling(source)
            store.append_snapshot(snapshot)

            history = store.list_snapshots(
                source.name,
                limit=config.baseline.window_size,
                max_age_days=config.baseline.max_age_days,
                success_only=True,
            )

            decision = engine.analyze(snapshot, history, source)

            alert_results = pipeline.process(source, decision)

            if decision.status in (DecisionStatus.ANOMALY, DecisionStatus.WARNING):
                has_anomaly = True

            # Serialize metrics with datetime handling
            serialized_metrics = {}
            for k, v in snapshot.metrics.items():
                if isinstance(v, datetime):
                    serialized_metrics[k] = v.isoformat()
                else:
                    serialized_metrics[k] = v

            results.append({
                "source": source.name,
                "status": decision.status.value,
                "metrics": serialized_metrics,
                "reasons": [r.to_dict() for r in decision.reasons],
                "alerts": alert_results,
                "duration_ms": snapshot.metadata.get("duration_ms"),
            })

        if json_output:
            console.print(json.dumps({"results": results}, indent=2))
        else:
            _print_check_results(results, dry_run)

        store.close()

        if has_anomaly:
            return 2
        return 0

    except Exception as e:
        error_console.print(f"[red]Error:[/red] {e}")
        if verbose:
            import traceback
            error_console.print(traceback.format_exc())
        return 1


def _is_due(schedule: str, store: SQLiteStateStore, source_name: str, now: datetime) -> bool:
    """Check if source is due for checking based on schedule."""
    last = store.get_last_snapshot(source_name)
    if last is None:
        return True

    cron = croniter(schedule, last.collected_at)
    next_run_result = cron.get_next(datetime)
    if not isinstance(next_run_result, datetime):
        return True

    if next_run_result.tzinfo is None:
        next_run_result = next_run_result.replace(tzinfo=timezone.utc)

    return now >= next_run_result


def _print_check_results(results: list[dict[str, Any]], dry_run: bool) -> None:
    """Print check results in human-readable format."""
    if not results:
        console.print("[dim]No sources checked[/dim]")
        return

    console.print(f"\n[bold]Checked {len(results)} source(s)[/bold]\n")

    for result in results:
        status = result["status"]
        if status == "OK":
            status_str = "[green]OK[/green]"
        elif status == "WARNING":
            status_str = "[yellow]WARNING[/yellow]"
        else:
            status_str = "[red]ANOMALY[/red]"

        console.print(f"[bold]{result['source']}[/bold]  {status_str}")

        metrics = result["metrics"]
        if "row_count" in metrics:
            console.print(f"  Row count: {metrics['row_count']:,}")
        if "latest_timestamp" in metrics:
            ts = metrics["latest_timestamp"]
            if isinstance(ts, str):
                console.print(f"  Latest data: {ts}")
            else:
                console.print(f"  Latest data: {ts.isoformat()}")

        if result["duration_ms"]:
            console.print(f"  Duration: {result['duration_ms']}ms")

        for reason in result["reasons"]:
            console.print(f"  [yellow]→ {reason['message']}[/yellow]")

        if result["alerts"]:
            if dry_run:
                targets = ", ".join(result["alerts"].keys())
                console.print(f"  [dim]Would alert: {targets}[/dim]")
            else:
                for target, success in result["alerts"].items():
                    if success:
                        console.print(f"  [green]✓ Sent to {target}[/green]")
                    else:
                        console.print(f"  [red]✗ Failed: {target}[/red]")

        console.print()

    ok_count = sum(1 for r in results if r["status"] == "OK")
    warn_count = sum(1 for r in results if r["status"] == "WARNING")
    anomaly_count = sum(1 for r in results if r["status"] == "ANOMALY")

    summary = f"Summary: {ok_count} OK"
    if warn_count:
        summary += f", {warn_count} WARNING"
    if anomaly_count:
        summary += f", {anomaly_count} ANOMALY"
    console.print(summary)


def run_daemon(config_path: Path, health_port: int | None = None) -> None:
    """Run agent in daemon mode."""
    from datafold.cli.main import setup_logging

    store, config = get_storage(config_path)
    setup_logging(config.agent.log_level)

    console.print("[bold]DataFold Agent[/bold] starting...")
    console.print(f"  Agent ID: {config.agent.id}")
    console.print(f"  Sources: {len(config.sources)}")
    console.print(f"  Webhooks: {len(config.alerting.webhooks)}")

    running = True

    def signal_handler(sig: int, frame: Any) -> None:
        nonlocal running
        console.print("\n[yellow]Shutting down...[/yellow]")
        running = False

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    connector = SQLConnector()
    engine = DetectionEngine(config.baseline)
    pipeline = AlertingPipeline(
        config=config.alerting,
        store=store,
        agent_id=config.agent.id,
    )

    console.print("[green]Agent running. Press Ctrl+C to stop.[/green]\n")

    while running:
        now = datetime.now(timezone.utc)

        for source in config.sources:
            if not source.enabled:
                continue

            if not _is_due(source.schedule, store, source.name, now):
                continue

            logger.info(f"Checking source: {source.name}")

            try:
                snapshot = connector.collect_with_error_handling(source)
                store.append_snapshot(snapshot)

                history = store.list_snapshots(
                    source.name,
                    limit=config.baseline.window_size,
                    max_age_days=config.baseline.max_age_days,
                    success_only=True,
                )

                decision = engine.analyze(snapshot, history, source)
                pipeline.process(source, decision)

                logger.info(
                    f"Source {source.name}: {decision.status.value} "
                    f"(row_count={snapshot.row_count})"
                )

            except Exception as e:
                logger.error(f"Error checking {source.name}: {e}")

        time.sleep(60)

    store.close()
    console.print("[green]Agent stopped.[/green]")


def show_status(config_path: Path, json_output: bool = False) -> None:
    """Show current status of all sources."""
    store, config = get_storage(config_path)

    statuses = []
    for source in config.sources:
        last = store.get_last_snapshot(source.name)
        if last:
            statuses.append({
                "source": source.name,
                "last_check": last.collected_at.isoformat(),
                "status": last.collect_status.value,
                "row_count": last.row_count,
                "enabled": source.enabled,
            })
        else:
            statuses.append({
                "source": source.name,
                "last_check": None,
                "status": "NEVER_CHECKED",
                "row_count": None,
                "enabled": source.enabled,
            })

    if json_output:
        console.print(json.dumps(statuses, indent=2))
    else:
        table = Table(title="Source Status")
        table.add_column("Source")
        table.add_column("Last Check")
        table.add_column("Status")
        table.add_column("Row Count")
        table.add_column("Enabled")

        for s in statuses:
            status_style = "green" if s["status"] == "SUCCESS" else "red"
            table.add_row(
                str(s["source"]),
                str(s["last_check"]) if s["last_check"] else "-",
                f"[{status_style}]{s['status']}[/{status_style}]",
                str(s["row_count"]) if s["row_count"] else "-",
                "Yes" if s["enabled"] else "No",
            )

        console.print(table)

    store.close()


def show_history(
    config_path: Path,
    source_name: str,
    limit: int,
    json_output: bool = False,
) -> None:
    """Show snapshot history for a source."""
    store, config = get_storage(config_path)

    snapshots = store.list_snapshots(
        source_name,
        limit=limit,
        max_age_days=365,
        success_only=False,
    )

    if json_output:
        data = [
            {
                "collected_at": s.collected_at.isoformat(),
                "status": s.collect_status.value,
                "metrics": s.metrics,
            }
            for s in snapshots
        ]
        console.print(json.dumps(data, indent=2))
    else:
        if not snapshots:
            console.print(f"[dim]No history for source: {source_name}[/dim]")
            store.close()
            return

        table = Table(title=f"History: {source_name}")
        table.add_column("Time")
        table.add_column("Status")
        table.add_column("Row Count")
        table.add_column("Latest Data")

        for s in snapshots:
            status_style = "green" if s.is_success else "red"
            table.add_row(
                s.collected_at.strftime("%Y-%m-%d %H:%M:%S"),
                f"[{status_style}]{s.collect_status.value}[/{status_style}]",
                str(s.row_count) if s.row_count else "-",
                s.latest_timestamp.strftime("%Y-%m-%d %H:%M") if s.latest_timestamp else "-",
            )

        console.print(table)

    store.close()


def explain_source(
    config_path: Path,
    source_name: str,
    json_output: bool = False,
) -> None:
    """Explain baseline and thresholds for a source."""
    store, config = get_storage(config_path)

    source_config = None
    for s in config.sources:
        if s.name == source_name:
            source_config = s
            break

    if not source_config:
        error_console.print(f"[red]Error:[/red] Source not found: {source_name}")
        store.close()
        return

    history = store.list_snapshots(
        source_name,
        limit=config.baseline.window_size,
        max_age_days=config.baseline.max_age_days,
        success_only=True,
    )

    engine = DetectionEngine(config.baseline)
    baseline = engine._calculate_baseline(history)

    if json_output:
        data = {
            "source": source_name,
            "config": {
                "freshness": {
                    "max_age_hours": source_config.freshness.max_age_hours,
                    "factor": source_config.freshness.factor,
                },
                "volume": {
                    "min_row_count": source_config.volume.min_row_count,
                    "deviation_factor": source_config.volume.deviation_factor,
                },
            },
            "baseline": baseline.to_dict(),
            "snapshot_count": len(history),
        }
        console.print(json.dumps(data, indent=2))
    else:
        console.print(f"\n[bold]Source: {source_name}[/bold]\n")

        console.print("[bold]Configuration:[/bold]")
        console.print(f"  Schedule: {source_config.schedule}")
        console.print(f"  Freshness max age: {source_config.freshness.max_age_hours}h")
        console.print(f"  Volume min: {source_config.volume.min_row_count}")
        console.print(f"  Deviation factor: {source_config.volume.deviation_factor}")

        console.print(f"\n[bold]Baseline (from {baseline.snapshot_count} snapshots):[/bold]")
        if baseline.snapshot_count > 0:
            console.print(f"  Row count median: {baseline.row_count_median:,.0f}")
            console.print(f"  Row count range: {baseline.row_count_min:,.0f} - {baseline.row_count_max:,.0f}")
            if baseline.row_count_stddev:
                console.print(f"  Row count stddev: {baseline.row_count_stddev:,.1f}")
            if baseline.expected_interval_seconds:
                hours = baseline.expected_interval_seconds / 3600
                console.print(f"  Expected interval: {hours:.1f}h")
        else:
            console.print("  [dim]No baseline data yet[/dim]")

        console.print("\n[bold]Snapshots in baseline:[/bold]")
        for snap in history[:5]:
            console.print(f"  {snap.collected_at.strftime('%Y-%m-%d %H:%M')} - {snap.row_count:,} rows")
        if len(history) > 5:
            console.print(f"  ... and {len(history) - 5} more")

    store.close()


def test_webhook_delivery(
    config_path: Path,
    target_name: str | None = None,
) -> None:
    """Send test webhook payload."""
    from datafold.alerting.webhook import WebhookDelivery
    from datafold.config import resolve_env_vars

    store, config = get_storage(config_path)

    webhooks = config.alerting.webhooks
    if target_name:
        webhooks = [w for w in webhooks if w.name == target_name]
        if not webhooks:
            error_console.print(f"[red]Error:[/red] Webhook not found: {target_name}")
            return

    delivery = WebhookDelivery()

    for webhook in webhooks:
        console.print(f"\nTesting webhook: [bold]{webhook.name}[/bold]")

        payload = WebhookPayload(
            event_type=EventType.INFO,
            timestamp=datetime.now(timezone.utc),
            source_name="test-source",
            source_type="test",
            decision={"status": "OK", "reasons": [], "confidence": 1.0},
            metrics={"row_count": 1000, "test": True},
            baseline_summary={},
            agent_id=config.agent.id,
        )

        from datafold.config import WebhookConfig

        resolved_webhook = WebhookConfig(
            name=webhook.name,
            url=resolve_env_vars(webhook.url),
            secret=resolve_env_vars(webhook.secret) if webhook.secret else None,
            events=webhook.events,
            timeout_seconds=webhook.timeout_seconds,
        )

        result = delivery.deliver(payload, resolved_webhook)

        if result.success:
            console.print(f"  [green]✓ Success[/green] (status: {result.status_code}, latency: {result.latency_ms}ms)")
        else:
            console.print(f"  [red]✗ Failed[/red]: {result.error}")

    store.close()


def run_purge(config_path: Path, dry_run: bool = False) -> None:
    """Run retention cleanup."""
    store, config = get_storage(config_path)

    if dry_run:
        console.print("[dim]Dry run: would delete old snapshots[/dim]")
        console.print(f"  Retention: {config.retention.days} days")
        console.print(f"  Min keep: {config.retention.min_snapshots} per source")
    else:
        deleted = store.purge_retention(
            days=config.retention.days,
            min_keep=config.retention.min_snapshots,
        )
        console.print(f"[green]Purged {deleted} old records[/green]")

    store.close()


def run_migrate(config_path: Path) -> None:
    """Run storage migrations."""
    store, config = get_storage(config_path)

    version = store.get_schema_version()
    console.print(f"[green]Storage schema version: {version}[/green]")

    store.close()
