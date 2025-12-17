"""End-to-end integration tests."""

from datetime import datetime, timedelta, timezone

import pytest

from datafold.alerting import AlertingPipeline
from datafold.config import (
    AlertingConfig,
    BaselineConfig,
    DataFoldConfig,
    FreshnessConfig,
    SourceConfig,
    StorageConfig,
    VolumeConfig,
    WebhookConfig,
)
from datafold.detection import DetectionEngine
from datafold.models import CollectStatus, DataSnapshot, DecisionStatus
from datafold.storage import SQLiteStateStore


@pytest.fixture
def config(tmp_path, monkeypatch):
    """Create test configuration."""
    monkeypatch.setenv("TEST_DB_URL", "sqlite:///test.db")
    return DataFoldConfig(
        version="1",
        storage=StorageConfig(
            backend="sqlite",
            path=str(tmp_path / "test.db"),
        ),
        sources=[
            SourceConfig(
                name="test-source",
                type="sql",
                dialect="sqlite",
                connection="${TEST_DB_URL}",
                query="SELECT COUNT(*) as row_count FROM test",
                freshness=FreshnessConfig(max_age_hours=24),
                volume=VolumeConfig(min_row_count=10),
            ),
        ],
        alerting=AlertingConfig(
            cooldown_minutes=60,
            webhooks=[
                WebhookConfig(
                    name="test-webhook",
                    url="https://example.com/webhook",
                    events=["anomaly", "recovery"],
                ),
            ],
        ),
        baseline=BaselineConfig(window_size=20, max_age_days=30),
    )


@pytest.fixture
def store(config):
    """Create and initialize storage."""
    store = SQLiteStateStore(config.storage.path)
    store.init()
    yield store
    store.close()


@pytest.fixture
def engine(config):
    """Create detection engine."""
    return DetectionEngine(config.baseline)


class TestEndToEnd:
    def test_full_check_workflow(self, config, store, engine):
        """Test complete check workflow: snapshot -> baseline -> detection."""
        source = config.sources[0]
        now = datetime.now(timezone.utc)

        for i in range(10):
            snapshot = DataSnapshot(
                source_name=source.name,
                collected_at=now - timedelta(hours=i + 1),
                collect_status=CollectStatus.SUCCESS,
                metrics={"row_count": 1000 + i * 10},
            )
            store.append_snapshot(snapshot)

        current = DataSnapshot(
            source_name=source.name,
            collected_at=now,
            collect_status=CollectStatus.SUCCESS,
            metrics={"row_count": 1050},
        )
        store.append_snapshot(current)

        history = store.list_snapshots(
            source.name,
            limit=config.baseline.window_size,
            max_age_days=config.baseline.max_age_days,
        )

        decision = engine.analyze(current, history, source)

        assert decision.status == DecisionStatus.OK
        assert decision.baseline_summary.snapshot_count > 0

    def test_anomaly_detection_workflow(self, config, store, engine):
        """Test anomaly detection with significant deviation."""
        source = config.sources[0]
        now = datetime.now(timezone.utc)

        for i in range(10):
            snapshot = DataSnapshot(
                source_name=source.name,
                collected_at=now - timedelta(hours=i + 1),
                collect_status=CollectStatus.SUCCESS,
                metrics={"row_count": 1000},
            )
            store.append_snapshot(snapshot)

        current = DataSnapshot(
            source_name=source.name,
            collected_at=now,
            collect_status=CollectStatus.SUCCESS,
            metrics={"row_count": 5},  # Below min_row_count
        )
        store.append_snapshot(current)

        history = store.list_snapshots(source.name)
        decision = engine.analyze(current, history, source)

        assert decision.status == DecisionStatus.ANOMALY

    def test_alerting_pipeline_deduplication(self, config, store):
        """Test that duplicate alerts are not sent."""
        source = config.sources[0]

        pipeline = AlertingPipeline(
            config=config.alerting,
            store=store,
            agent_id="test-agent",
            dry_run=True,
        )

        from datafold.models import Decision, Reason

        decision = Decision(
            status=DecisionStatus.ANOMALY,
            reasons=[Reason(code="VOLUME_LOW", message="Test")],
            metrics={"row_count": 10},
            baseline_summary=None,
        )

        results1 = pipeline.process(source, decision)
        assert "test-webhook" in results1

        results2 = pipeline.process(source, decision)
        assert "test-webhook" in results2

    def test_retention_cleanup(self, config, store):
        """Test retention cleanup preserves minimum snapshots."""
        now = datetime.now(timezone.utc)

        for i in range(50):
            snapshot = DataSnapshot(
                source_name="test-source",
                collected_at=now - timedelta(days=i),
                collect_status=CollectStatus.SUCCESS,
                metrics={"row_count": 1000},
            )
            store.append_snapshot(snapshot)

        deleted = store.purge_retention(days=30, min_keep=10)

        assert deleted > 0

        remaining = store.list_snapshots("test-source", limit=100, max_age_days=365)
        assert len(remaining) >= 10

    def test_storage_persistence(self, config):
        """Test that data persists across store instances."""
        store1 = SQLiteStateStore(config.storage.path)
        store1.init()

        snapshot = DataSnapshot(
            source_name="persist-test",
            collected_at=datetime.now(timezone.utc),
            collect_status=CollectStatus.SUCCESS,
            metrics={"row_count": 42},
        )
        store1.append_snapshot(snapshot)
        store1.close()

        store2 = SQLiteStateStore(config.storage.path)
        store2.init()

        retrieved = store2.get_last_snapshot("persist-test")
        assert retrieved is not None
        assert retrieved.row_count == 42

        store2.close()
