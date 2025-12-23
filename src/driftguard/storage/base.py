"""Abstract base class for state storage."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from driftguard.models import AlertState, DataSnapshot, DeliveryResult


class StateStore(ABC):
    """Abstract interface for state storage backends."""

    @abstractmethod
    def init(self) -> None:
        """Initialize the storage backend."""

    @abstractmethod
    def migrate(self) -> None:
        """Apply any pending migrations."""

    @abstractmethod
    def healthcheck(self) -> bool:
        """Check if storage is accessible and healthy."""

    @abstractmethod
    def close(self) -> None:
        """Close the storage connection."""

    @abstractmethod
    def append_snapshot(self, snapshot: DataSnapshot) -> int:
        """Store a snapshot and return its ID."""

    @abstractmethod
    def get_last_snapshot(self, source_name: str) -> DataSnapshot | None:
        """Get the most recent snapshot for a source."""

    @abstractmethod
    def list_snapshots(
        self,
        source_name: str,
        limit: int = 20,
        max_age_days: int = 30,
        success_only: bool = True,
    ) -> list[DataSnapshot]:
        """List recent snapshots for baseline calculation."""

    @abstractmethod
    def get_alert_state(self, source_name: str, target_name: str) -> AlertState | None:
        """Get alert state for a source-target pair."""

    @abstractmethod
    def set_alert_state(self, state: AlertState) -> None:
        """Update alert state for a source-target pair."""

    @abstractmethod
    def log_delivery(
        self,
        source_name: str,
        target_name: str,
        event_type: str,
        payload_hash: str,
        result: DeliveryResult,
    ) -> None:
        """Log a webhook delivery attempt."""

    @abstractmethod
    def purge_retention(self, days: int, min_keep: int) -> int:
        """Delete old snapshots, return count deleted."""

    @abstractmethod
    def get_schema_version(self) -> int:
        """Get current schema version."""
