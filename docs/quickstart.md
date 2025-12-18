# Quick Start

Get DataFold running in 5 minutes.

## Installation

### Using pip

```bash
# Basic installation
pip install datafold-agent

# With PostgreSQL support
pip install "datafold-agent[postgres]"

# With all database drivers
pip install "datafold-agent[all]"
```

### Using Docker

```bash
docker pull ghcr.io/datafold/agent:latest
```

## Step 1: Initialize Configuration

```bash
datafold init
```

This creates `datafold.yaml` with example configuration.

## Step 2: Configure Your Data Source

Edit `datafold.yaml`:

```yaml
version: "1"

agent:
  id: my-agent

storage:
  backend: sqlite
  path: ./datafold.db

sources:
  - name: orders
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

## Step 3: Set Environment Variables

```bash
export DATABASE_URL="postgresql://user:pass@localhost:5432/mydb"
export SLACK_WEBHOOK_URL="https://hooks.slack.com/services/..."
```

## Step 4: Validate Configuration

```bash
datafold validate
```

Expected output:
```
✓ Configuration is valid
  Sources: 1
  Webhooks: 1
```

## Step 5: Run First Check

```bash
datafold check --force
```

The `--force` flag runs immediately regardless of schedule.

Example output:
```
Checked 1 source(s)

orders  OK
  Row count: 1,247
  Latest data: 2024-01-15T10:30:00Z
  Duration: 45ms

Summary: 1 OK, 0 ANOMALY
```

## Step 6: Start Daemon Mode

For continuous monitoring:

```bash
datafold run
```

Or with Docker:

```bash
docker run -d \
  -v $(pwd)/datafold.yaml:/app/datafold.yaml:ro \
  -v datafold-data:/app/data \
  -e DATABASE_URL="$DATABASE_URL" \
  -e SLACK_WEBHOOK_URL="$SLACK_WEBHOOK_URL" \
  ghcr.io/datafold/agent:latest run
```

## Step 7: View Status

```bash
datafold status
```

```
┏━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━━━┓
┃ Source ┃ Last Check           ┃ Status  ┃ Row Count ┃
┡━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━━━┩
│ orders │ 2024-01-15T10:30:00Z │ SUCCESS │ 1,247     │
└────────┴──────────────────────┴─────────┴───────────┘
```

## Next Steps

- [Configuration Reference](./configuration.md) - Full config options
- [CLI Reference](./cli-reference.md) - All commands
- [Deployment](./deployment.md) - Production setup
- [Alerting](./alerting.md) - Webhook configuration
