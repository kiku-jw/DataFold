"""Tests for CLI commands."""


import pytest
from click.testing import CliRunner

from datafold.cli.main import cli


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def config_file(tmp_path):
    config_content = """
version: "1"
agent:
  id: test-agent
storage:
  backend: sqlite
  path: ./test.db
sources: []
alerting:
  webhooks: []
"""
    config_path = tmp_path / "datafold.yaml"
    config_path.write_text(config_content)
    return config_path


class TestCLI:
    def test_version(self, runner):
        result = runner.invoke(cli, ["--version"])
        assert result.exit_code == 0
        assert "datafold" in result.output.lower()

    def test_help(self, runner):
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "check" in result.output
        assert "run" in result.output
        assert "validate" in result.output

    def test_init_creates_config(self, runner, tmp_path):
        config_path = tmp_path / "datafold.yaml"

        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(cli, ["init", "--path", str(config_path)])

        assert result.exit_code == 0
        assert config_path.exists()
        assert "Created config file" in result.output

    def test_init_fails_if_exists(self, runner, config_file):
        result = runner.invoke(cli, ["init", "--path", str(config_file)])

        assert result.exit_code == 1
        assert "already exists" in result.output

    def test_validate_valid_config(self, runner, config_file):
        result = runner.invoke(cli, ["--config", str(config_file), "validate"])

        assert result.exit_code == 0
        assert "Config valid" in result.output

    def test_validate_missing_config(self, runner, tmp_path):
        missing_path = tmp_path / "nonexistent.yaml"

        result = runner.invoke(cli, ["--config", str(missing_path), "validate"])

        assert result.exit_code == 1

    def test_render_config(self, runner, config_file):
        result = runner.invoke(cli, ["--config", str(config_file), "render-config"])

        assert result.exit_code == 0
        assert "Agent" in result.output
        assert "Storage" in result.output

    def test_check_with_no_sources(self, runner, config_file, tmp_path):
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(cli, ["--config", str(config_file), "check"])

        assert result.exit_code == 0

    def test_check_dry_run(self, runner, config_file, tmp_path):
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(cli, ["--config", str(config_file), "check", "--dry-run"])

        assert result.exit_code == 0


class TestCLICommands:
    def test_status_command(self, runner, config_file, tmp_path):
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(cli, ["--config", str(config_file), "status"])

        assert result.exit_code == 0

    def test_history_unknown_source(self, runner, config_file, tmp_path):
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(
                cli,
                ["--config", str(config_file), "history", "unknown-source"]
            )

        assert result.exit_code == 0
        assert "No history" in result.output

    def test_purge_dry_run(self, runner, config_file, tmp_path):
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(
                cli,
                ["--config", str(config_file), "purge", "--dry-run"]
            )

        assert result.exit_code == 0
        assert "Dry run" in result.output

    def test_migrate_command(self, runner, config_file, tmp_path):
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(cli, ["--config", str(config_file), "migrate"])

        assert result.exit_code == 0
        assert "schema version" in result.output.lower()
