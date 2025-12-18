"""Integration tests for CLI commands."""


import pytest
import yaml
from click.testing import CliRunner

from datafold.cli.main import cli


@pytest.fixture
def runner():
    return CliRunner()

@pytest.fixture
def full_config(tmp_path):
    config = {
        "version": "1",
        "agent": {"id": "test-cli-agent"},
        "storage": {"backend": "sqlite", "path": str(tmp_path / "datafold.db")},
        "sources": [
            {
                "name": "test_src",
                "type": "sql",
                "dialect": "sqlite",
                "connection": str(tmp_path / "source.db"),
                "query": "SELECT 1 as row_count",
                "schedule": "*/1 * * * *"
            }
        ],
        "alerting": {"webhooks": []}
    }
    config_path = tmp_path / "datafold.yaml"
    with open(config_path, "w") as f:
        yaml.dump(config, f)

    # Create source db
    import sqlite3
    conn = sqlite3.connect(tmp_path / "source.db")
    conn.execute("CREATE TABLE test (id INT)")
    conn.commit()
    conn.close()

    return config_path

class TestCLIIntegration:
    def test_check_command_execution(self, runner, full_config):
        result = runner.invoke(cli, ["--config", str(full_config), "check"])
        assert result.exit_code == 0
        assert "Checked 1 source(s)" in result.output
        assert "test_src" in result.output
        assert "OK" in result.output

    def test_status_command_with_history(self, runner, full_config):
        # Run check first to populate history
        runner.invoke(cli, ["--config", str(full_config), "check"])

        result = runner.invoke(cli, ["--config", str(full_config), "status"])
        assert result.exit_code == 0
        assert "Source Status" in result.output
        assert "test_src" in result.output

    def test_explain_command(self, runner, full_config):
        runner.invoke(cli, ["--config", str(full_config), "check"])

        result = runner.invoke(cli, ["--config", str(full_config), "explain", "--source", "test_src"])
        assert result.exit_code == 0
        assert "Source: test_src" in result.output
        assert "Baseline" in result.output

    def test_validate_with_env_vars(self, runner, tmp_path, monkeypatch):
        monkeypatch.setenv("DB_URL", "sqlite:///test.db")
        config_content = """
version: "1"
sources:
  - name: test
    connection: ${DB_URL}
    query: SELECT 1
"""
        config_path = tmp_path / "env_config.yaml"
        config_path.write_text(config_content)

        result = runner.invoke(cli, ["--config", str(config_path), "validate"])
        assert result.exit_code == 0
        assert "Config valid" in result.output
