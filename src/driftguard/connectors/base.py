"""Base connector interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from driftguard.config import SourceConfig
    from driftguard.models import DataSnapshot


class ConnectorError(Exception):
    """Base exception for connector errors."""

    def __init__(self, message: str, code: str = "CONNECTOR_ERROR") -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class ConnectionError(ConnectorError):
    """Failed to connect to data source."""

    def __init__(self, message: str) -> None:
        super().__init__(message, "CONNECTION_ERROR")


class QueryError(ConnectorError):
    """Query execution failed."""

    def __init__(self, message: str) -> None:
        super().__init__(message, "QUERY_ERROR")


class TimeoutError(ConnectorError):
    """Query timed out."""

    def __init__(self, message: str) -> None:
        super().__init__(message, "TIMEOUT_ERROR")


class ValidationError(ConnectorError):
    """Query result validation failed."""

    def __init__(self, message: str) -> None:
        super().__init__(message, "VALIDATION_ERROR")


class Connector(ABC):
    """Abstract base class for data source connectors."""

    @abstractmethod
    def collect(self, config: SourceConfig) -> DataSnapshot:
        """Collect data from source and return normalized snapshot."""

    @abstractmethod
    def test_connection(self, config: SourceConfig) -> bool:
        """Test if connection to source is possible."""
