"""Core detection engine for anomaly detection."""

from __future__ import annotations

import statistics
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from datafold.models import (
    BaselineSummary,
    CollectStatus,
    Decision,
    DecisionStatus,
    Reason,
)

if TYPE_CHECKING:
    from datafold.config import BaselineConfig, SourceConfig
    from datafold.models import DataSnapshot


class DetectionEngine:
    """Core detection engine for freshness and volume anomalies."""

    def __init__(self, baseline_config: BaselineConfig) -> None:
        self.window_size = baseline_config.window_size
        self.max_age_days = baseline_config.max_age_days

    def analyze(
        self,
        current: DataSnapshot,
        history: list[DataSnapshot],
        source_config: SourceConfig,
    ) -> Decision:
        """Analyze current snapshot against baseline."""
        reasons: list[Reason] = []

        if current.collect_status == CollectStatus.COLLECT_FAILED:
            return Decision(
                status=DecisionStatus.ANOMALY,
                reasons=[
                    Reason(
                        code="COLLECT_FAILED",
                        message=f"Failed to collect data: {current.metadata.get('error_message', 'Unknown error')}",
                    )
                ],
                metrics=current.metrics,
                baseline_summary=None,
                confidence=1.0,
            )

        baseline = self._calculate_baseline(history)

        freshness_reasons = self._check_freshness(current, history, source_config, baseline)
        reasons.extend(freshness_reasons)

        volume_reasons = self._check_volume(current, source_config, baseline)
        reasons.extend(volume_reasons)

        schema_reasons = self._check_schema_drift(current, history, source_config)
        reasons.extend(schema_reasons)

        status = self._determine_status(reasons)

        return Decision(
            status=status,
            reasons=reasons,
            metrics=current.metrics,
            baseline_summary=baseline,
            confidence=self._calculate_confidence(baseline),
        )

    def _calculate_baseline(self, history: list[DataSnapshot]) -> BaselineSummary:
        """Calculate baseline statistics from historical snapshots."""
        if not history:
            return BaselineSummary(
                snapshot_count=0,
                row_count_median=None,
                row_count_min=None,
                row_count_max=None,
                row_count_stddev=None,
                expected_interval_seconds=None,
                oldest_snapshot_at=None,
                newest_snapshot_at=None,
            )

        row_counts = [s.row_count for s in history if s.row_count is not None]

        row_count_median = statistics.median(row_counts) if row_counts else None
        row_count_min = min(row_counts) if row_counts else None
        row_count_max = max(row_counts) if row_counts else None
        row_count_stddev = (
            statistics.stdev(row_counts) if len(row_counts) > 1 else 0.0
        )

        intervals: list[float] = []
        sorted_history = sorted(history, key=lambda s: s.collected_at)
        for i in range(1, len(sorted_history)):
            delta = (
                sorted_history[i].collected_at - sorted_history[i - 1].collected_at
            )
            intervals.append(delta.total_seconds())

        expected_interval = statistics.median(intervals) if intervals else None

        return BaselineSummary(
            snapshot_count=len(history),
            row_count_median=row_count_median,
            row_count_min=row_count_min,
            row_count_max=row_count_max,
            row_count_stddev=row_count_stddev,
            expected_interval_seconds=expected_interval,
            oldest_snapshot_at=min(s.collected_at for s in history),
            newest_snapshot_at=max(s.collected_at for s in history),
        )

    def _check_freshness(
        self,
        current: DataSnapshot,
        history: list[DataSnapshot],
        config: SourceConfig,
        baseline: BaselineSummary,
    ) -> list[Reason]:
        """Check for freshness anomalies."""
        reasons: list[Reason] = []
        now = datetime.now(timezone.utc)

        if config.freshness.max_age_hours is not None:
            latest_ts = current.latest_timestamp
            if latest_ts:
                age_hours = (now - latest_ts).total_seconds() / 3600
                if age_hours > config.freshness.max_age_hours:
                    reasons.append(
                        Reason(
                            code="STALE_DATA",
                            message=f"Data is {age_hours:.1f}h old, exceeds max age of {config.freshness.max_age_hours}h",
                        )
                    )

        if baseline.expected_interval_seconds and history:
            last_snapshot = max(history, key=lambda s: s.collected_at)
            gap = (current.collected_at - last_snapshot.collected_at).total_seconds()
            expected = baseline.expected_interval_seconds * config.freshness.factor

            if gap > expected:
                gap_hours = gap / 3600
                expected_hours = expected / 3600
                reasons.append(
                    Reason(
                        code="COLLECTION_GAP",
                        message=f"Gap since last collection: {gap_hours:.1f}h, expected max: {expected_hours:.1f}h",
                    )
                )

        if current.latest_timestamp and history:
            latest_timestamps = [
                s.latest_timestamp for s in history if s.latest_timestamp
            ]
            if latest_timestamps:
                last_data_ts = max(latest_timestamps)
                if current.latest_timestamp <= last_data_ts:
                    reasons.append(
                        Reason(
                            code="NO_NEW_DATA",
                            message=f"No new data since {last_data_ts.isoformat()}",
                        )
                    )

        return reasons

    def _check_volume(
        self,
        current: DataSnapshot,
        config: SourceConfig,
        baseline: BaselineSummary,
    ) -> list[Reason]:
        """Check for volume anomalies."""
        reasons: list[Reason] = []
        row_count = current.row_count

        if row_count is None:
            return reasons

        if config.volume.min_row_count is not None and row_count < config.volume.min_row_count:
            reasons.append(
                Reason(
                    code="BELOW_MIN_VOLUME",
                    message=f"Row count {row_count} is below minimum threshold of {config.volume.min_row_count}",
                )
            )

        if baseline.row_count_median is not None and baseline.snapshot_count >= 3:
            if baseline.row_count_stddev is not None and baseline.row_count_stddev > 0:
                z_score = abs(row_count - baseline.row_count_median) / baseline.row_count_stddev
                if z_score > config.volume.deviation_factor:
                    if row_count < baseline.row_count_median:
                        pct_change = (
                            (baseline.row_count_median - row_count)
                            / baseline.row_count_median
                            * 100
                        )
                        reasons.append(
                            Reason(
                                code="VOLUME_LOW",
                                message=f"Row count {row_count} is {pct_change:.1f}% below baseline median ({baseline.row_count_median:.0f})",
                            )
                        )
                    else:
                        pct_change = (
                            (row_count - baseline.row_count_median)
                            / baseline.row_count_median
                            * 100
                        )
                        reasons.append(
                            Reason(
                                code="VOLUME_HIGH",
                                message=f"Row count {row_count} is {pct_change:.1f}% above baseline median ({baseline.row_count_median:.0f})",
                            )
                        )
            elif row_count == 0 and baseline.row_count_median > 0:
                reasons.append(
                    Reason(
                        code="ZERO_VOLUME",
                        message=f"Row count is 0, baseline median is {baseline.row_count_median:.0f}",
                    )
                )

        return reasons

    def _check_schema_drift(
        self,
        current: DataSnapshot,
        history: list[DataSnapshot],
        config: SourceConfig,
    ) -> list[Reason]:
        """Check for schema drift anomalies."""
        reasons: list[Reason] = []

        if not config.schema_drift:
            return reasons

        current_schema = current.schema
        if not current_schema:
            return reasons

        # Find last successful snapshot with schema in history
        last_schema = None
        for s in reversed(history):
            if s.collect_status == CollectStatus.SUCCESS and s.schema:
                last_schema = s.schema
                break

        if not last_schema:
            return reasons

        if current_schema != last_schema:
            # Simple check: column names and types
            current_cols = {c["name"]: c["type"] for c in current_schema}
            last_cols = {c["name"]: c["type"] for c in last_schema}

            added = set(current_cols.keys()) - set(last_cols.keys())
            removed = set(last_cols.keys()) - set(current_cols.keys())
            changed = {
                k for k in current_cols.keys() & last_cols.keys()
                if current_cols[k] != last_cols[k]
            }

            msgs = []
            if added:
                msgs.append(f"added: {', '.join(sorted(added))}")
            if removed:
                msgs.append(f"removed: {', '.join(sorted(removed))}")
            if changed:
                msgs.append(f"changed: {', '.join(sorted(changed))}")

            reasons.append(
                Reason(
                    code="SCHEMA_DRIFT",
                    message=f"Schema changed ({'; '.join(msgs)})",
                )
            )

        return reasons

    def _determine_status(self, reasons: list[Reason]) -> DecisionStatus:
        """Determine overall status from reasons."""
        if not reasons:
            return DecisionStatus.OK

        critical_codes = {
            "COLLECT_FAILED",
            "ZERO_VOLUME",
            "BELOW_MIN_VOLUME",
            "STALE_DATA",
            "SCHEMA_DRIFT",
        }

        for reason in reasons:
            if reason.code in critical_codes:
                return DecisionStatus.ANOMALY

        warning_codes = {
            "VOLUME_LOW",
            "VOLUME_HIGH",
            "COLLECTION_GAP",
            "NO_NEW_DATA",
        }

        for reason in reasons:
            if reason.code in warning_codes:
                return DecisionStatus.WARNING

        return DecisionStatus.OK

    def _calculate_confidence(self, baseline: BaselineSummary) -> float:
        """Calculate confidence based on baseline quality."""
        if baseline.snapshot_count == 0:
            return 0.0
        if baseline.snapshot_count < 3:
            return 0.3
        if baseline.snapshot_count < 10:
            return 0.6
        if baseline.snapshot_count < 20:
            return 0.8
        return 0.95
