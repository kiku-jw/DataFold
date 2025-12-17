"""SQLite state storage backend."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from datafold.models import AlertState, CollectStatus, DataSnapshot, DecisionStatus
from datafold.storage.base import StateStore

if TYPE_CHECKING:
    from datafold.models import DeliveryResult

SCHEMA_VERSION = 1

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS schema_meta (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_name TEXT NOT NULL,
    collected_at TEXT NOT NULL,
    collect_status TEXT NOT NULL,
    row_count INTEGER,
    latest_timestamp TEXT,
    metrics_json TEXT NOT NULL,
    metadata_json TEXT NOT NULL,
    duration_ms INTEGER,
    error_code TEXT,
    error_message TEXT
);

CREATE INDEX IF NOT EXISTS idx_snapshots_source_time
    ON snapshots(source_name, collected_at DESC);
CREATE INDEX IF NOT EXISTS idx_snapshots_source_status_time
    ON snapshots(source_name, collect_status, collected_at DESC);

CREATE TABLE IF NOT EXISTS alert_state (
    source_name TEXT NOT NULL,
    target_name TEXT NOT NULL,
    notified_status TEXT NOT NULL,
    notified_reason_hash TEXT NOT NULL,
    last_change_at TEXT NOT NULL,
    last_sent_at TEXT,
    cooldown_until TEXT,
    PRIMARY KEY (source_name, target_name)
);

CREATE TABLE IF NOT EXISTS deliveries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_name TEXT NOT NULL,
    target_name TEXT NOT NULL,
    event_type TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    sent_at TEXT NOT NULL,
    success INTEGER NOT NULL,
    status_code INTEGER,
    latency_ms INTEGER,
    error_message TEXT,
    attempts INTEGER NOT NULL DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_deliveries_source_time
    ON deliveries(source_name, sent_at DESC);
"""


class SQLiteStateStore(StateStore):
    """SQLite-based state storage."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._conn: sqlite3.Connection | None = None

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        """Get a database connection."""
        if self._conn is None:
            raise RuntimeError("Storage not initialized. Call init() first.")
        yield self._conn

    def init(self) -> None:
        """Initialize the SQLite database."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self.migrate()

    def migrate(self) -> None:
        """Apply schema migrations."""
        with self._connection() as conn:
            current_version = self._get_schema_version_internal(conn)

            if current_version == 0:
                conn.executescript(SCHEMA_SQL)
                conn.execute(
                    "INSERT OR REPLACE INTO schema_meta (version, applied_at) VALUES (?, ?)",
                    (SCHEMA_VERSION, datetime.now(timezone.utc).isoformat()),
                )
                conn.commit()

    def _get_schema_version_internal(self, conn: sqlite3.Connection) -> int:
        """Get schema version from connection."""
        try:
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_meta'"
            )
            if cursor.fetchone() is None:
                return 0
            cursor = conn.execute("SELECT MAX(version) FROM schema_meta")
            result = cursor.fetchone()
            return result[0] if result and result[0] else 0
        except sqlite3.OperationalError:
            return 0

    def healthcheck(self) -> bool:
        """Check if database is accessible."""
        try:
            with self._connection() as conn:
                conn.execute("SELECT 1")
                return True
        except Exception:
            return False

    def close(self) -> None:
        """Close the database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None

    def append_snapshot(self, snapshot: DataSnapshot) -> int:
        """Store a snapshot."""
        with self._connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO snapshots (
                    source_name, collected_at, collect_status, row_count,
                    latest_timestamp, metrics_json, metadata_json, duration_ms,
                    error_code, error_message
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot.source_name,
                    snapshot.collected_at.isoformat(),
                    snapshot.collect_status.value,
                    snapshot.row_count,
                    snapshot.latest_timestamp.isoformat() if snapshot.latest_timestamp else None,
                    json.dumps(snapshot.metrics),
                    json.dumps(snapshot.metadata),
                    snapshot.metadata.get("duration_ms"),
                    snapshot.metadata.get("error_code"),
                    snapshot.metadata.get("error_message"),
                ),
            )
            conn.commit()
            return cursor.lastrowid or 0

    def get_last_snapshot(self, source_name: str) -> DataSnapshot | None:
        """Get most recent snapshot."""
        with self._connection() as conn:
            cursor = conn.execute(
                """
                SELECT * FROM snapshots
                WHERE source_name = ?
                ORDER BY collected_at DESC
                LIMIT 1
                """,
                (source_name,),
            )
            row = cursor.fetchone()
            return self._row_to_snapshot(row) if row else None

    def list_snapshots(
        self,
        source_name: str,
        limit: int = 20,
        max_age_days: int = 30,
        success_only: bool = True,
    ) -> list[DataSnapshot]:
        """List recent snapshots for baseline."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)

        with self._connection() as conn:
            if success_only:
                cursor = conn.execute(
                    """
                    SELECT * FROM snapshots
                    WHERE source_name = ?
                    AND collect_status = 'SUCCESS'
                    AND collected_at >= ?
                    ORDER BY collected_at DESC
                    LIMIT ?
                    """,
                    (source_name, cutoff.isoformat(), limit),
                )
            else:
                cursor = conn.execute(
                    """
                    SELECT * FROM snapshots
                    WHERE source_name = ?
                    AND collected_at >= ?
                    ORDER BY collected_at DESC
                    LIMIT ?
                    """,
                    (source_name, cutoff.isoformat(), limit),
                )

            return [self._row_to_snapshot(row) for row in cursor.fetchall()]

    def _row_to_snapshot(self, row: sqlite3.Row) -> DataSnapshot:
        """Convert database row to DataSnapshot."""
        return DataSnapshot(
            id=row["id"],
            source_name=row["source_name"],
            collected_at=datetime.fromisoformat(row["collected_at"]),
            collect_status=CollectStatus(row["collect_status"]),
            metrics=json.loads(row["metrics_json"]),
            metadata=json.loads(row["metadata_json"]),
        )

    def get_alert_state(self, source_name: str, target_name: str) -> AlertState | None:
        """Get alert state for source-target pair."""
        with self._connection() as conn:
            cursor = conn.execute(
                """
                SELECT * FROM alert_state
                WHERE source_name = ? AND target_name = ?
                """,
                (source_name, target_name),
            )
            row = cursor.fetchone()
            return self._row_to_alert_state(row) if row else None

    def set_alert_state(self, state: AlertState) -> None:
        """Update alert state."""
        with self._connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO alert_state (
                    source_name, target_name, notified_status, notified_reason_hash,
                    last_change_at, last_sent_at, cooldown_until
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    state.source_name,
                    state.target_name,
                    state.notified_status.value,
                    state.notified_reason_hash,
                    state.last_change_at.isoformat(),
                    state.last_sent_at.isoformat() if state.last_sent_at else None,
                    state.cooldown_until.isoformat() if state.cooldown_until else None,
                ),
            )
            conn.commit()

    def _row_to_alert_state(self, row: sqlite3.Row) -> AlertState:
        """Convert database row to AlertState."""
        return AlertState(
            source_name=row["source_name"],
            target_name=row["target_name"],
            notified_status=DecisionStatus(row["notified_status"]),
            notified_reason_hash=row["notified_reason_hash"],
            last_change_at=datetime.fromisoformat(row["last_change_at"]),
            last_sent_at=(
                datetime.fromisoformat(row["last_sent_at"]) if row["last_sent_at"] else None
            ),
            cooldown_until=(
                datetime.fromisoformat(row["cooldown_until"]) if row["cooldown_until"] else None
            ),
        )

    def log_delivery(
        self,
        source_name: str,
        target_name: str,
        event_type: str,
        payload_hash: str,
        result: DeliveryResult,
    ) -> None:
        """Log a webhook delivery."""
        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO deliveries (
                    source_name, target_name, event_type, payload_hash,
                    sent_at, success, status_code, latency_ms, error_message, attempts
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    source_name,
                    target_name,
                    event_type,
                    payload_hash,
                    datetime.now(timezone.utc).isoformat(),
                    1 if result.success else 0,
                    result.status_code,
                    result.latency_ms,
                    result.error,
                    result.attempts,
                ),
            )
            conn.commit()

    def purge_retention(self, days: int, min_keep: int) -> int:
        """Delete old snapshots while keeping minimum per source."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        total_deleted = 0

        with self._connection() as conn:
            cursor = conn.execute("SELECT DISTINCT source_name FROM snapshots")
            sources = [row[0] for row in cursor.fetchall()]

            for source in sources:
                cursor = conn.execute(
                    """
                    SELECT id FROM snapshots
                    WHERE source_name = ?
                    ORDER BY collected_at DESC
                    """,
                    (source,),
                )
                ids = [row[0] for row in cursor.fetchall()]

                if len(ids) <= min_keep:
                    continue

                keep_ids = set(ids[:min_keep])

                cursor = conn.execute(
                    """
                    SELECT id FROM snapshots
                    WHERE source_name = ?
                    AND collected_at < ?
                    AND id NOT IN ({})
                    """.format(",".join("?" * len(keep_ids))),
                    (source, cutoff.isoformat(), *keep_ids),
                )
                to_delete = [row[0] for row in cursor.fetchall()]

                if to_delete:
                    conn.execute(
                        "DELETE FROM snapshots WHERE id IN ({})".format(
                            ",".join("?" * len(to_delete))
                        ),
                        to_delete,
                    )
                    total_deleted += len(to_delete)

            cursor = conn.execute(
                "DELETE FROM deliveries WHERE sent_at < ?",
                (cutoff.isoformat(),),
            )
            total_deleted += cursor.rowcount

            conn.commit()

        return total_deleted

    def get_schema_version(self) -> int:
        """Get current schema version."""
        with self._connection() as conn:
            return self._get_schema_version_internal(conn)
