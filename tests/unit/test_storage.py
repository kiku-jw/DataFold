"""Tests for state storage."""

from datetime import datetime, timedelta, timezone

import pytest

from driftguard.models import (
    AlertState,
    CollectStatus,
    DataSnapshot,
    DecisionStatus,
    DeliveryResult,
)
from driftguard.storage.sqlite import SQLiteStateStore


@pytest.fixture
def store(tmp_path):
    """Create a temporary SQLite store."""
    db_path = tmp_path / "test.db"
    store = SQLiteStateStore(db_path)
    store.init()
    yield store
    store.close()


class TestSQLiteStateStore:
    def test_init_creates_tables(self, store):
        assert store.healthcheck() is True
        assert store.get_schema_version() == 1

    def test_append_and_get_snapshot(self, store):
        snapshot = DataSnapshot(
            source_name="test",
            collected_at=datetime.now(timezone.utc),
            collect_status=CollectStatus.SUCCESS,
            metrics={"row_count": 100},
            metadata={"duration_ms": 50},
        )

        snapshot_id = store.append_snapshot(snapshot)
        assert snapshot_id > 0

        retrieved = store.get_last_snapshot("test")
        assert retrieved is not None
        assert retrieved.source_name == "test"
        assert retrieved.row_count == 100

    def test_get_last_snapshot_returns_none_for_unknown(self, store):
        result = store.get_last_snapshot("nonexistent")
        assert result is None

    def test_list_snapshots_success_only(self, store):
        now = datetime.now(timezone.utc)

        store.append_snapshot(DataSnapshot(
            source_name="test",
            collected_at=now - timedelta(hours=2),
            collect_status=CollectStatus.SUCCESS,
            metrics={"row_count": 100},
        ))
        store.append_snapshot(DataSnapshot(
            source_name="test",
            collected_at=now - timedelta(hours=1),
            collect_status=CollectStatus.COLLECT_FAILED,
            metrics={},
        ))
        store.append_snapshot(DataSnapshot(
            source_name="test",
            collected_at=now,
            collect_status=CollectStatus.SUCCESS,
            metrics={"row_count": 200},
        ))

        snapshots = store.list_snapshots("test", success_only=True)
        assert len(snapshots) == 2
        assert all(s.is_success for s in snapshots)

    def test_list_snapshots_respects_limit(self, store):
        now = datetime.now(timezone.utc)

        for i in range(10):
            store.append_snapshot(DataSnapshot(
                source_name="test",
                collected_at=now - timedelta(hours=i),
                collect_status=CollectStatus.SUCCESS,
                metrics={"row_count": 100 + i},
            ))

        snapshots = store.list_snapshots("test", limit=5)
        assert len(snapshots) == 5

    def test_list_snapshots_respects_max_age(self, store):
        now = datetime.now(timezone.utc)

        store.append_snapshot(DataSnapshot(
            source_name="test",
            collected_at=now - timedelta(days=60),
            collect_status=CollectStatus.SUCCESS,
            metrics={"row_count": 100},
        ))
        store.append_snapshot(DataSnapshot(
            source_name="test",
            collected_at=now - timedelta(days=10),
            collect_status=CollectStatus.SUCCESS,
            metrics={"row_count": 200},
        ))

        snapshots = store.list_snapshots("test", max_age_days=30)
        assert len(snapshots) == 1
        assert snapshots[0].row_count == 200


class TestAlertState:
    def test_get_set_alert_state(self, store):
        state = AlertState(
            source_name="test",
            target_name="slack",
            notified_status=DecisionStatus.OK,
            notified_reason_hash="abc123",
            last_change_at=datetime.now(timezone.utc),
            last_sent_at=None,
            cooldown_until=None,
        )

        store.set_alert_state(state)

        retrieved = store.get_alert_state("test", "slack")
        assert retrieved is not None
        assert retrieved.notified_status == DecisionStatus.OK
        assert retrieved.notified_reason_hash == "abc123"

    def test_get_alert_state_returns_none_for_unknown(self, store):
        result = store.get_alert_state("unknown", "unknown")
        assert result is None

    def test_update_alert_state(self, store):
        state1 = AlertState(
            source_name="test",
            target_name="slack",
            notified_status=DecisionStatus.OK,
            notified_reason_hash="abc",
            last_change_at=datetime.now(timezone.utc),
            last_sent_at=None,
            cooldown_until=None,
        )
        store.set_alert_state(state1)

        state2 = AlertState(
            source_name="test",
            target_name="slack",
            notified_status=DecisionStatus.ANOMALY,
            notified_reason_hash="xyz",
            last_change_at=datetime.now(timezone.utc),
            last_sent_at=datetime.now(timezone.utc),
            cooldown_until=None,
        )
        store.set_alert_state(state2)

        retrieved = store.get_alert_state("test", "slack")
        assert retrieved.notified_status == DecisionStatus.ANOMALY


class TestDeliveryLog:
    def test_log_delivery(self, store):
        result = DeliveryResult(
            success=True,
            status_code=200,
            latency_ms=150,
            attempts=1,
        )

        store.log_delivery(
            source_name="test",
            target_name="slack",
            event_type="anomaly",
            payload_hash="abc123",
            result=result,
        )


class TestRetention:
    def test_purge_retention(self, store):
        now = datetime.now(timezone.utc)

        for i in range(20):
            store.append_snapshot(DataSnapshot(
                source_name="test",
                collected_at=now - timedelta(days=i * 5),
                collect_status=CollectStatus.SUCCESS,
                metrics={"row_count": 100},
            ))

        store.purge_retention(days=30, min_keep=10)

        remaining = store.list_snapshots("test", limit=100, max_age_days=365)
        assert len(remaining) >= 10
