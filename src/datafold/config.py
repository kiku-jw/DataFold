"""Configuration models and loading for DataFold Agent."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator

ENV_VAR_PATTERN = re.compile(r"\$\{([^}]+)\}")
CREDENTIALS_PATTERN = re.compile(r"://[^/]+:[^/]+@")


class AgentConfig(BaseModel):
    """Agent identification and logging configuration."""

    id: str = "datafold-agent"
    log_level: str = "info"
    log_format: str = "text"


class StorageConfig(BaseModel):
    """State storage configuration."""

    backend: str = "sqlite"
    path: str = "./datafold.db"
    connection: str | None = None


class FreshnessConfig(BaseModel):
    """Freshness detection configuration."""

    max_age_hours: float | None = None
    factor: float = 2.0


class VolumeConfig(BaseModel):
    """Volume detection configuration."""

    min_row_count: int | None = None
    deviation_factor: float = 3.0


class SourceConfig(BaseModel):
    """Data source configuration."""

    name: str
    type: str = "sql"
    dialect: str = "postgres"
    connection: str
    query: str
    schedule: str = "*/15 * * * *"
    freshness: FreshnessConfig = Field(default_factory=FreshnessConfig)
    volume: VolumeConfig = Field(default_factory=VolumeConfig)
    schema_drift: bool = True
    enabled: bool = True

    @field_validator("connection")
    @classmethod
    def validate_connection(cls, v: str) -> str:
        if CREDENTIALS_PATTERN.search(v) and "${" not in v:
            raise ValueError(
                "Connection string appears to contain credentials. "
                "Use environment variables: ${DB_URL}"
            )
        return v


class WebhookConfig(BaseModel):
    """Webhook target configuration."""

    name: str
    url: str
    secret: str | None = None
    events: list[str] = Field(default_factory=lambda: ["anomaly", "recovery"])
    timeout_seconds: int = 10

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        if CREDENTIALS_PATTERN.search(v) and "${" not in v:
            raise ValueError("Webhook URL should use environment variables: ${WEBHOOK_URL}")
        return v


class AlertingConfig(BaseModel):
    """Alerting configuration."""

    cooldown_minutes: int = 60
    webhooks: list[WebhookConfig] = Field(default_factory=list)


class RetentionConfig(BaseModel):
    """Data retention configuration."""

    days: int = 30
    min_snapshots: int = 10


class BaselineConfig(BaseModel):
    """Baseline calculation configuration."""

    window_size: int = 20
    max_age_days: int = 30


class DataFoldConfig(BaseModel):
    """Root configuration for DataFold Agent."""

    version: str = "1"
    agent: AgentConfig = Field(default_factory=AgentConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    sources: list[SourceConfig] = Field(default_factory=list)
    alerting: AlertingConfig = Field(default_factory=AlertingConfig)
    retention: RetentionConfig = Field(default_factory=RetentionConfig)
    baseline: BaselineConfig = Field(default_factory=BaselineConfig)

    @model_validator(mode="after")
    def validate_version(self) -> DataFoldConfig:
        if self.version != "1":
            raise ValueError(f"Unsupported config version: {self.version}. Expected: 1")
        return self


def resolve_env_vars(value: str) -> str:
    """Resolve ${VAR} patterns in a string."""

    def replace(match: re.Match[str]) -> str:
        var_name = match.group(1)
        env_value = os.environ.get(var_name)
        if env_value is None:
            raise ValueError(f"Environment variable not set: {var_name}")
        return env_value

    return ENV_VAR_PATTERN.sub(replace, value)


def resolve_config_env_vars(config: DataFoldConfig) -> DataFoldConfig:
    """Resolve all environment variables in config."""
    data = config.model_dump()

    def resolve_recursive(obj: Any) -> Any:
        if isinstance(obj, str):
            return resolve_env_vars(obj)
        if isinstance(obj, dict):
            return {k: resolve_recursive(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [resolve_recursive(v) for v in obj]
        return obj

    resolved_data = resolve_recursive(data)
    return DataFoldConfig.model_validate(resolved_data)


def mask_secrets(value: str) -> str:
    """Mask sensitive parts of connection strings."""
    masked = re.sub(r"://([^:]+):([^@]+)@", r"://\1:***@", value)
    return masked


def load_config(path: Path) -> DataFoldConfig:
    """Load and validate configuration from YAML file."""
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    with open(path) as f:
        raw_config = yaml.safe_load(f)

    if raw_config is None:
        raise ValueError("Config file is empty")

    return DataFoldConfig.model_validate(raw_config)


def find_config_file() -> Path | None:
    """Find config file in standard locations."""
    locations = [
        Path("./datafold.yaml"),
        Path("./datafold.yml"),
        Path.home() / ".config" / "datafold" / "datafold.yaml",
        Path("/etc/datafold/datafold.yaml"),
    ]

    for loc in locations:
        if loc.exists():
            return loc

    return None


def generate_example_config() -> str:
    """Generate example configuration."""
    return """version: "1"

agent:
  id: my-datafold-agent
  log_level: info

storage:
  backend: sqlite
  path: ./datafold.db

sources:
  - name: orders_daily
    type: sql
    dialect: postgres
    connection: ${DATABASE_URL}
    query: |
      SELECT
        COUNT(*) as row_count,
        MAX(created_at) as latest_timestamp
      FROM orders
      WHERE created_at >= NOW() - INTERVAL '24 hours'
    schedule: "0 */6 * * *"
    freshness:
      max_age_hours: 8
    volume:
      min_row_count: 100

alerting:
  cooldown_minutes: 60
  webhooks:
    - name: slack
      url: ${SLACK_WEBHOOK_URL}
      secret: ${WEBHOOK_SECRET}
      events: [anomaly, recovery]

retention:
  days: 30
  min_snapshots: 10

baseline:
  window_size: 20
  max_age_days: 30
"""
