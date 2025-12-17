"""Core data models for DataFold Agent."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class CollectStatus(str, Enum):
    SUCCESS = "SUCCESS"
    COLLECT_FAILED = "COLLECT_FAILED"


class DecisionStatus(str, Enum):
    OK = "OK"
    WARNING = "WARNING"
    ANOMALY = "ANOMALY"
    UNKNOWN = "UNKNOWN"


class EventType(str, Enum):
    ANOMALY = "anomaly"
    WARNING = "warning"
    RECOVERY = "recovery"
    INFO = "info"


@dataclass
class DataSnapshot:
    """Normalized snapshot from any data source."""

    source_name: str
    collected_at: datetime
    collect_status: CollectStatus
    metrics: dict[str, Any]
    metadata: dict[str, Any] = field(default_factory=dict)
    id: int | None = None

    @property
    def row_count(self) -> int | None:
        return self.metrics.get("row_count")

    @property
    def latest_timestamp(self) -> datetime | None:
        ts = self.metrics.get("latest_timestamp")
        if isinstance(ts, datetime):
            return ts
        if isinstance(ts, str):
            try:
                return datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except ValueError:
                return None
        return None

    @property
    def is_success(self) -> bool:
        return self.collect_status == CollectStatus.SUCCESS


@dataclass
class Reason:
    """A single reason for a detection decision."""

    code: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}


@dataclass
class BaselineSummary:
    """Summary of baseline statistics."""

    snapshot_count: int
    row_count_median: float | None
    row_count_min: float | None
    row_count_max: float | None
    row_count_stddev: float | None
    expected_interval_seconds: float | None
    oldest_snapshot_at: datetime | None
    newest_snapshot_at: datetime | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "snapshot_count": self.snapshot_count,
            "row_count_median": self.row_count_median,
            "row_count_min": self.row_count_min,
            "row_count_max": self.row_count_max,
            "row_count_stddev": self.row_count_stddev,
            "expected_interval_seconds": self.expected_interval_seconds,
        }


@dataclass
class Decision:
    """Result of detection engine analysis."""

    status: DecisionStatus
    reasons: list[Reason]
    metrics: dict[str, Any]
    baseline_summary: BaselineSummary | None
    confidence: float = 1.0

    @property
    def reason_hash(self) -> str:
        data = {
            "status": self.status.value,
            "reason_codes": sorted(r.code for r in self.reasons),
        }
        return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()[:16]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "reasons": [r.to_dict() for r in self.reasons],
            "confidence": self.confidence,
        }


@dataclass
class AlertState:
    """Per-source, per-target alert state for deduplication."""

    source_name: str
    target_name: str
    notified_status: DecisionStatus
    notified_reason_hash: str
    last_change_at: datetime
    last_sent_at: datetime | None
    cooldown_until: datetime | None

    def should_alert(
        self, decision: Decision, cooldown_minutes: int, now: datetime | None = None
    ) -> bool:
        now = now or datetime.now(timezone.utc)

        if self.cooldown_until and now < self.cooldown_until:
            return False

        return not (decision.status == self.notified_status and decision.reason_hash == self.notified_reason_hash)


@dataclass
class DeliveryResult:
    """Result of webhook delivery attempt."""

    success: bool
    status_code: int | None = None
    error: str | None = None
    latency_ms: int | None = None
    attempts: int = 1


@dataclass
class WebhookPayload:
    """Webhook payload structure."""

    version: str = "1"
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    event_type: EventType = EventType.INFO
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    source_name: str = ""
    source_type: str = ""
    decision: dict[str, Any] = field(default_factory=dict)
    metrics: dict[str, Any] = field(default_factory=dict)
    baseline_summary: dict[str, Any] = field(default_factory=dict)
    agent_id: str = ""

    def to_canonical_json(self) -> str:
        data = {
            "version": self.version,
            "event_id": self.event_id,
            "event_type": self.event_type.value,
            "timestamp": self.timestamp.isoformat(),
            "source": {
                "name": self.source_name,
                "type": self.source_type,
            },
            "decision": self.decision,
            "metrics": self.metrics,
            "baseline": self.baseline_summary,
            "context": {
                "agent_id": self.agent_id,
            },
        }
        return json.dumps(data, sort_keys=True, separators=(",", ":"))

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = json.loads(self.to_canonical_json())
        return result
