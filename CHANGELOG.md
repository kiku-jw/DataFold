# Changelog

All notable changes to DriftGuard Agent will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2025-01-15

### Added

- **Core Functionality**
  - SQL connector supporting PostgreSQL, MySQL, ClickHouse, and SQLite
  - Freshness detection with configurable `max_age_hours` and baseline factor
  - Volume detection with `min_row_count` and statistical deviation thresholds
  - Schema drift detection for column additions, removals, and type changes
  - Behavioral baseline learning from historical snapshots
  - SQLite state storage with migrations and retention policies

- **Alerting**
  - Webhook delivery with HMAC-SHA256 signatures
  - Retry logic (3 attempts with exponential backoff)
  - Per-source, per-target deduplication
  - Configurable cooldown periods
  - Support for anomaly, warning, recovery, and info events

- **CLI Commands**
  - `init` - Create configuration file
  - `validate` - Validate configuration
  - `render-config` - Show resolved config with masked secrets
  - `check` - Run checks on data sources
  - `run` - Start daemon mode with internal scheduler
  - `status` - Show current source status
  - `history` - Show snapshot history
  - `explain` - Explain baseline and thresholds
  - `test-webhook` - Send test payload
  - `purge` - Clean old snapshots
  - `migrate` - Apply storage migrations

- **Infrastructure**
  - Docker multi-stage build with non-root user
  - Docker Compose development setup
  - GitHub Actions CI (lint, test, build)
  - Kubernetes CronJob example

- **Security**
  - Environment variable requirement for secrets
  - Validation rejects hardcoded passwords
  - HMAC signing for webhook payloads

### Documentation

- Comprehensive documentation (11 guides)
- README with quick start
- Configuration reference
- CLI reference
- Deployment guides (Docker, Kubernetes, systemd)
- Troubleshooting guide
- Python API reference

## [Unreleased]

### Planned for 0.2.0

- Prometheus metrics endpoint
- PostgreSQL storage backend (for multi-agent setups)
- BigQuery connector
- Snowflake connector

### Planned for 0.3.0

- Distribution drift detection (ML-based)
- Web UI dashboard
- Slack bot integration
- Kafka connector
