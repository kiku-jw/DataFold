"""Mock tests for SQL connector."""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from driftguard.config import SourceConfig
from driftguard.connectors.sql import SQLConnector


@pytest.fixture
def connector():
    return SQLConnector(timeout_seconds=5)

@pytest.fixture
def source_config(monkeypatch):
    monkeypatch.setenv("DB_URL", "postgresql://user:pass@localhost:5432/db")
    return SourceConfig(
        name="test_sql",
        type="sql",
        dialect="postgres",
        connection="${DB_URL}",
        query="SELECT COUNT(*) as row_count FROM my_table",
    )

class TestSQLConnectorMock:
    @patch("driftguard.connectors.sql.create_engine")
    def test_collect_success_postgres(self, mock_create_engine, connector, source_config):
        # Mock engine and connection
        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_create_engine.return_value = mock_engine
        mock_engine.connect.return_value.__enter__.return_value = mock_conn

        # Mock result execution
        mock_result = MagicMock()
        mock_conn.execute.return_value = mock_result
        mock_result.fetchone.return_value = [100, datetime(2024, 1, 1, tzinfo=timezone.utc)]
        mock_result.keys.return_value = ["row_count", "latest_timestamp"]

        snapshot = connector.collect(source_config)

        assert snapshot.source_name == "test_sql"
        assert snapshot.row_count == 100
        assert snapshot.latest_timestamp == datetime(2024, 1, 1, tzinfo=timezone.utc)
        assert snapshot.schema == [
            {"name": "row_count", "type": "int"},
            {"name": "latest_timestamp", "type": "datetime"}
        ]

    @patch("driftguard.connectors.sql.create_engine")
    def test_collect_failure_connection(self, mock_create_engine, connector, source_config):
        from sqlalchemy.exc import OperationalError
        mock_create_engine.side_effect = OperationalError("Connection error", None, None)

        snapshot = connector.collect_with_error_handling(source_config)

        assert snapshot.collect_status.value == "COLLECT_FAILED"
        assert "Database connection failed" in snapshot.metadata["error_message"]

    def test_build_connection_string_sqlite(self, connector):
        cfg = SourceConfig(
            name="sqlite",
            type="sql",
            dialect="sqlite",
            connection="data.db",
            query="SELECT 1"
        )
        conn_str = connector._build_connection_string(cfg)
        assert conn_str == "sqlite:///data.db"

    def test_extract_metrics_various_names(self, connector, source_config):
        # Test mapping 'count' to 'row_count'
        metrics = connector._extract_metrics({"count": 42}, source_config)
        assert metrics["row_count"] == 42

        # Test mapping 'max_timestamp' to 'latest_timestamp'
        ts = datetime(2024, 1, 1)
        metrics = connector._extract_metrics({"row_count": 10, "max_timestamp": ts}, source_config)
        assert metrics["latest_timestamp"] == ts.replace(tzinfo=timezone.utc)
