# DataFold Agent

**Automated data quality & drift detection.** Watches incoming data streams, detects anomalies, unexpected spikes, missing values, and schema drift. Ideal for marketplaces, analytics dashboards, financial data, and event pipelines.

[![CI](https://github.com/datafold/agent/actions/workflows/ci.yaml/badge.svg)](https://github.com/datafold/agent/actions/workflows/ci.yaml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## Why DataFold?

Data can be **syntactically valid but semantically dead**. Your ETL job succeeded, Airflow is green, but:

- The dashboard shows yesterday's data (and no one noticed)
- Row count dropped 90% (but didn't hit zero)
- A critical column is now 30% NULL
- The upstream changed their schema silently

**DataFold catches these silent failures before your business does.**

## Features

- **Freshness Detection** — Alerts when data stops updating
- **Volume Monitoring** — Catches unexpected spikes and drops
- **Baseline Learning** — No manual thresholds, learns from your data
- **Webhook Alerts** — Slack, PagerDuty, or any HTTP endpoint
- **Zero UI Required** — CLI-first, DevOps-friendly
- **Lightweight** — Single binary, SQLite storage, no dependencies

## Quick Start

### Installation

```bash
pip install datafold-agent

# With database drivers
pip install "datafold-agent[postgres]"
pip install "datafold-agent[all]"  # postgres, mysql, clickhouse
```

### Initialize

```bash
datafold init
```

### Configure

Edit `datafold.yaml`:

```yaml
version: "1"

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
  webhooks:
    - name: slack
      url: ${SLACK_WEBHOOK_URL}
      events: [anomaly, recovery]
```

### Run

```bash
# Single check
datafold check

# Daemon mode
datafold run

# Check specific source
datafold check --source orders_daily
```

## CLI Commands

| Command | Description |
|---------|-------------|
| `datafold init` | Create config file |
| `datafold validate` | Validate configuration |
| `datafold check` | Run checks on all sources |
| `datafold run` | Start daemon with scheduler |
| `datafold status` | Show current status |
| `datafold history <source>` | Show snapshot history |
| `datafold explain --source X` | Explain baseline and thresholds |
| `datafold test-webhook` | Send test payload |
| `datafold purge` | Clean old snapshots |

## Configuration

### Environment Variables

Secrets must use environment variables:

```yaml
connection: ${DATABASE_URL}      # Required
url: ${SLACK_WEBHOOK_URL}        # Required for webhooks
```

### Source Options

```yaml
sources:
  - name: my_source
    type: sql
    dialect: postgres           # postgres, mysql, clickhouse
    connection: ${DB_URL}
    query: |
      SELECT COUNT(*) as row_count,
             MAX(updated_at) as latest_timestamp
      FROM my_table
    schedule: "*/15 * * * *"    # Cron expression
    freshness:
      max_age_hours: 24         # Hard limit (optional)
      factor: 2.0               # Baseline multiplier
    volume:
      min_row_count: 100        # Hard minimum (optional)
      deviation_factor: 3.0     # Stddev multiplier
```

### Webhook Payload

```json
{
  "version": "1",
  "event_id": "uuid",
  "event_type": "anomaly",
  "timestamp": "2024-01-15T10:30:00Z",
  "source": {
    "name": "orders_daily",
    "type": "postgres"
  },
  "decision": {
    "status": "ANOMALY",
    "reasons": [
      {"code": "VOLUME_LOW", "message": "Row count 150 is 85% below baseline"}
    ]
  },
  "metrics": {
    "row_count": 150,
    "baseline_row_count": 1000
  }
}
```

## Docker

```bash
docker run -v ./datafold.yaml:/app/datafold.yaml \
  -e DATABASE_URL="..." \
  -e SLACK_WEBHOOK_URL="..." \
  ghcr.io/datafold/agent:latest run
```

### Docker Compose

```yaml
services:
  datafold:
    image: ghcr.io/datafold/agent:latest
    command: run
    environment:
      - DATABASE_URL=${DATABASE_URL}
      - SLACK_WEBHOOK_URL=${SLACK_WEBHOOK_URL}
    volumes:
      - ./datafold.yaml:/app/datafold.yaml:ro
      - datafold-data:/app/data
```

## Kubernetes

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: datafold-check
spec:
  schedule: "*/15 * * * *"
  jobTemplate:
    spec:
      template:
        spec:
          containers:
            - name: datafold
              image: ghcr.io/datafold/agent:latest
              command: ["datafold", "check"]
              envFrom:
                - secretRef:
                    name: datafold-secrets
```

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | All checks passed |
| 1 | Configuration or runtime error |
| 2 | Anomaly detected |

## Development

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Run linter
ruff check src tests

# Run type checker
mypy src
```

## License

MIT License. See [LICENSE](LICENSE) for details.
