"""Tests for detection engine."""

from datetime import datetime, timedelta, timezone

import pytest

from datafold.config import BaselineConfig, FreshnessConfig, SourceConfig, VolumeConfig
from datafold.detection.engine import DetectionEngine
from datafold.models import CollectStatus, DataSnapshot, DecisionStatus


@pytest.fixture
def engine():
    config = BaselineConfig(window_size=20, max_age_days=30)
    return DetectionEngine(config)


@pytest.fixture
def source_config(monkeypatch):
    monkeypatch.setenv("DB_URL", "postgresql://localhost/test")
    return SourceConfig(
        name="test",
        type="sql",
        dialect="postgres",
        connection="${DB_URL}",
        query="SELECT COUNT(*) as row_count FROM test",
        freshness=FreshnessConfig(max_age_hours=24, factor=2.0),
        volume=VolumeConfig(min_row_count=50, deviation_factor=3.0),
    )


def make_snapshot(
    row_count: int,
    hours_ago: float = 0,
    status: CollectStatus = CollectStatus.SUCCESS,
    latest_timestamp_hours_ago: float | None = None,
) -> DataSnapshot:
    now = datetime.now(timezone.utc)
    collected_at = now - timedelta(hours=hours_ago)

    metrics = {"row_count": row_count}
    if latest_timestamp_hours_ago is not None:
        metrics["latest_timestamp"] = (now - timedelta(hours=latest_timestamp_hours_ago)).isoformat()

    return DataSnapshot(
        source_name="test",
        collected_at=collected_at,
        collect_status=status,
        metrics=metrics,
    )


class TestDetectionEngine:
    def test_ok_when_within_baseline(self, engine, source_config):
        history = [make_snapshot(1000, hours_ago=i) for i in range(1, 11)]
        current = make_snapshot(1050)

        decision = engine.analyze(current, history, source_config)

        assert decision.status == DecisionStatus.OK
        assert len(decision.reasons) == 0

    def test_anomaly_on_collect_failed(self, engine, source_config):
        history = [make_snapshot(1000, hours_ago=i) for i in range(1, 11)]
        current = make_snapshot(0, status=CollectStatus.COLLECT_FAILED)
        current.metadata["error_message"] = "Connection refused"

        decision = engine.analyze(current, history, source_config)

        assert decision.status == DecisionStatus.ANOMALY
        assert any(r.code == "COLLECT_FAILED" for r in decision.reasons)

    def test_anomaly_on_volume_below_minimum(self, engine, source_config):
        history = [make_snapshot(1000, hours_ago=i) for i in range(1, 11)]
        current = make_snapshot(30)  # Below min_row_count=50

        decision = engine.analyze(current, history, source_config)

        assert decision.status == DecisionStatus.ANOMALY
        assert any(r.code == "BELOW_MIN_VOLUME" for r in decision.reasons)

    def test_warning_on_volume_deviation(self, engine, source_config):
        # Use varying row counts to get non-zero stddev
        history = [make_snapshot(1000 + i * 50, hours_ago=i) for i in range(1, 11)]
        current = make_snapshot(100)  # Significant drop from ~1000-1500 range

        decision = engine.analyze(current, history, source_config)

        assert decision.status in (DecisionStatus.WARNING, DecisionStatus.ANOMALY)
        codes = [r.code for r in decision.reasons]
        assert "VOLUME_LOW" in codes or "BELOW_MIN_VOLUME" in codes

    def test_anomaly_on_stale_data(self, engine, source_config):
        history = [make_snapshot(1000, hours_ago=i, latest_timestamp_hours_ago=i)
                   for i in range(1, 11)]
        current = make_snapshot(1000, latest_timestamp_hours_ago=48)  # Data 48h old

        decision = engine.analyze(current, history, source_config)

        assert decision.status == DecisionStatus.ANOMALY
        assert any(r.code == "STALE_DATA" for r in decision.reasons)

    def test_zero_volume_is_anomaly(self, engine, source_config):
        history = [make_snapshot(1000, hours_ago=i) for i in range(1, 11)]
        current = make_snapshot(0)

        decision = engine.analyze(current, history, source_config)

        assert decision.status == DecisionStatus.ANOMALY
        codes = [r.code for r in decision.reasons]
        assert "ZERO_VOLUME" in codes or "BELOW_MIN_VOLUME" in codes


class TestBaselineCalculation:
    def test_empty_history(self, engine, source_config):
        current = make_snapshot(1000)

        decision = engine.analyze(current, [], source_config)

        assert decision.baseline_summary is not None
        assert decision.baseline_summary.snapshot_count == 0
        assert decision.confidence == 0.0

    def test_baseline_with_few_snapshots(self, engine, source_config):
        history = [make_snapshot(1000, hours_ago=i) for i in range(1, 3)]
        current = make_snapshot(1000)

        decision = engine.analyze(current, history, source_config)

        assert decision.baseline_summary.snapshot_count == 2
        assert decision.confidence < 0.5

    def test_baseline_stats_calculation(self, engine, source_config):
        history = [
            make_snapshot(800, hours_ago=3),
            make_snapshot(1000, hours_ago=2),
            make_snapshot(1200, hours_ago=1),
        ]
        current = make_snapshot(1000)

        decision = engine.analyze(current, history, source_config)

        baseline = decision.baseline_summary
        assert baseline.row_count_min == 800
        assert baseline.row_count_max == 1200
        assert baseline.row_count_median == 1000

    def test_confidence_increases_with_history(self, engine, source_config):
        decisions = []

        for n in [2, 5, 10, 25]:
            history = [make_snapshot(1000, hours_ago=i) for i in range(1, n + 1)]
            current = make_snapshot(1000)
            decision = engine.analyze(current, history, source_config)
            decisions.append(decision)

        confidences = [d.confidence for d in decisions]
        assert confidences == sorted(confidences)
