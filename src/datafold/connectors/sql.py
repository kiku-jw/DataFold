"""SQL database connector."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError, ProgrammingError

from datafold.config import SourceConfig, resolve_env_vars
from datafold.connectors.base import (
    ConnectionError,
    Connector,
    ConnectorError,
    QueryError,
    TimeoutError,
    ValidationError,
)
from datafold.models import CollectStatus, DataSnapshot

DIALECT_DRIVERS = {
    "postgres": "postgresql+psycopg2",
    "postgresql": "postgresql+psycopg2",
    "mysql": "mysql+pymysql",
    "clickhouse": "clickhouse+native",
    "sqlite": "sqlite",
}


class SQLConnector(Connector):
    """SQL database connector supporting multiple dialects."""

    def __init__(self, timeout_seconds: int = 30) -> None:
        self.timeout_seconds = timeout_seconds

    def collect(self, config: SourceConfig) -> DataSnapshot:
        """Execute query and collect metrics."""
        start_time = time.time()
        collected_at = datetime.now(timezone.utc)

        try:
            connection_string = self._build_connection_string(config)
            engine = create_engine(
                connection_string,
                connect_args=self._get_connect_args(config.dialect),
            )

            with engine.connect() as conn:
                result = conn.execute(text(config.query))
                row = result.fetchone()

                if row is None:
                    raise QueryError("Query returned no rows")

                columns = list(result.keys())
                row_dict = dict(zip(columns, row, strict=False))

                metrics = self._extract_metrics(row_dict, config)
                schema = [{"name": k, "type": str(type(v).__name__)} for k, v in row_dict.items()]

            duration_ms = int((time.time() - start_time) * 1000)

            return DataSnapshot(
                source_name=config.name,
                collected_at=collected_at,
                collect_status=CollectStatus.SUCCESS,
                metrics=metrics,
                metadata={
                    "duration_ms": duration_ms,
                    "connector_type": "sql",
                    "dialect": config.dialect,
                    "schema": schema,
                },
            )

        except ConnectorError:
            raise
        except OperationalError as e:
            error_msg = str(e)[:500]
            if "timeout" in error_msg.lower():
                raise TimeoutError(f"Query timed out: {error_msg}") from e
            raise ConnectionError(f"Database connection failed: {error_msg}") from e
        except ProgrammingError as e:
            raise QueryError(f"Query execution failed: {str(e)[:500]}") from e
        except Exception as e:
            raise ConnectorError(f"Unexpected error: {str(e)[:500]}") from e

    def collect_with_error_handling(self, config: SourceConfig) -> DataSnapshot:
        """Collect with graceful error handling, returns COLLECT_FAILED snapshot on error."""
        start_time = time.time()
        collected_at = datetime.now(timezone.utc)

        try:
            return self.collect(config)
        except ConnectorError as e:
            duration_ms = int((time.time() - start_time) * 1000)
            return DataSnapshot(
                source_name=config.name,
                collected_at=collected_at,
                collect_status=CollectStatus.COLLECT_FAILED,
                metrics={},
                metadata={
                    "duration_ms": duration_ms,
                    "connector_type": "sql",
                    "dialect": config.dialect,
                    "error_code": e.code,
                    "error_message": e.message[:500],
                },
            )

    def test_connection(self, config: SourceConfig) -> bool:
        """Test database connection."""
        try:
            connection_string = self._build_connection_string(config)
            engine = create_engine(
                connection_string,
                connect_args=self._get_connect_args(config.dialect),
            )
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return True
        except Exception:
            return False

    def _build_connection_string(self, config: SourceConfig) -> str:
        """Build SQLAlchemy connection string."""
        connection = resolve_env_vars(config.connection)

        parsed = urlparse(connection)
        if parsed.scheme and parsed.scheme in DIALECT_DRIVERS:
            return connection

        dialect = config.dialect.lower()
        if dialect not in DIALECT_DRIVERS:
            raise ConnectionError(f"Unsupported dialect: {dialect}")

        driver = DIALECT_DRIVERS[dialect]

        if "://" not in connection:
            if dialect == "sqlite":
                # SQLite needs sqlite:/// for relative, sqlite://// for absolute
                if connection.startswith("/"):
                    return f"{driver}:///{connection}"
                return f"{driver}:///{connection}"
            return f"{driver}://{connection}"

        return connection.replace(f"{parsed.scheme}://", f"{driver}://")

    def _get_connect_args(self, dialect: str) -> dict[str, Any]:
        """Get dialect-specific connection arguments."""
        args: dict[str, Any] = {}

        if dialect in ("postgres", "postgresql"):
            args["connect_timeout"] = self.timeout_seconds
        elif dialect == "mysql":
            args["connect_timeout"] = self.timeout_seconds
            args["read_timeout"] = self.timeout_seconds

        return args

    def _extract_metrics(
        self, row: dict[str, Any], config: SourceConfig
    ) -> dict[str, Any]:
        """Extract and validate metrics from query result."""
        metrics: dict[str, Any] = {}

        if "row_count" in row:
            metrics["row_count"] = self._to_int(row["row_count"])
        elif "count" in row:
            metrics["row_count"] = self._to_int(row["count"])
        else:
            for key, value in row.items():
                if "count" in key.lower():
                    metrics["row_count"] = self._to_int(value)
                    break

        if "row_count" not in metrics:
            raise ValidationError(
                "Query must return 'row_count' column. "
                "Use: SELECT COUNT(*) as row_count, ..."
            )

        if "latest_timestamp" in row:
            metrics["latest_timestamp"] = self._to_datetime(row["latest_timestamp"])
        elif "max_timestamp" in row:
            metrics["latest_timestamp"] = self._to_datetime(row["max_timestamp"])
        else:
            for key, value in row.items():
                if "timestamp" in key.lower() or "time" in key.lower():
                    ts = self._to_datetime(value)
                    if ts:
                        metrics["latest_timestamp"] = ts
                        break

        for key, value in row.items():
            if key not in ("row_count", "latest_timestamp", "count") and isinstance(value, (int, float)):
                metrics[key] = value

        return metrics

    def _to_int(self, value: Any) -> int:
        """Convert value to integer."""
        if value is None:
            return 0
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
        if isinstance(value, str):
            return int(float(value.replace(",", "")))
        return int(value)

    def _to_datetime(self, value: Any) -> datetime | None:
        """Convert value to datetime."""
        if value is None:
            return None
        if isinstance(value, datetime):
            if value.tzinfo is None:
                return value.replace(tzinfo=timezone.utc)
            return value
        if isinstance(value, str):
            try:
                dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt
            except ValueError:
                return None
        return None
