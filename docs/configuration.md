# Configuration Reference

Complete reference for `datafold.yaml` configuration.

## File Location

DataFold looks for configuration in this order:
1. `--config` CLI argument
2. `./datafold.yaml`
3. `./datafold.yml`
4. `~/.config/datafold/datafold.yaml`
5. `/etc/datafold/datafold.yaml`

## Full Schema

```yaml
version: "1"                    # Required, must be "1"

agent:
  id: my-agent                  # Agent identifier (for multi-agent setups)
  log_level: info               # debug, info, warn, error

storage:
  backend: sqlite               # sqlite (postgres planned)
  path: ./datafold.db           # Path to SQLite database

sources:                        # List of data sources to monitor
  - name: source_name           # Unique identifier
    type: sql                   # Source type (only sql for now)
    dialect: postgres           # postgres, mysql, clickhouse, sqlite
    connection: ${DB_URL}       # Connection string (use env vars!)
    query: |                    # SQL query returning row_count, latest_timestamp
      SELECT COUNT(*) as row_count,
             MAX(updated_at) as latest_timestamp
      FROM my_table
    schedule: "0 * * * *"       # Cron expression
    enabled: true               # Enable/disable without removing
    
    freshness:                  # Freshness detection settings
      max_age_hours: 24         # Hard limit - always alert if older
      factor: 2.0               # Baseline multiplier (default: 2.0)
    
    volume:                     # Volume detection settings
      min_row_count: 100        # Hard minimum - always alert if below
      deviation_factor: 3.0     # Stddev multiplier (default: 3.0)
    
    timeout_seconds: 30         # Query timeout (default: 30)

alerting:
  cooldown_minutes: 60          # Don't repeat same alert within window
  
  webhooks:                     # List of webhook targets
    - name: slack               # Unique identifier
      url: ${WEBHOOK_URL}       # Webhook URL (use env vars!)
      secret: ${WEBHOOK_SECRET} # Optional HMAC secret
      events:                   # Events to send
        - anomaly               # Status changed to ANOMALY
        - warning               # Status changed to WARNING  
        - recovery              # Status recovered to OK
        - info                  # Informational (test payloads)
      timeout_seconds: 10       # Request timeout (default: 10)

retention:
  days: 30                      # Keep snapshots for N days
  min_snapshots: 10             # Always keep at least N per source

baseline:
  window_size: 20               # Use last N snapshots for baseline
  max_age_days: 30              # Ignore snapshots older than N days
```

## Environment Variables

### Security Requirement

Secrets MUST use environment variable syntax:

```yaml
# ✅ Correct - uses env var
connection: ${DATABASE_URL}

# ❌ Wrong - hardcoded password (validation will fail)
connection: postgresql://user:password@host/db
```

### Syntax

```yaml
# Single variable
connection: ${DATABASE_URL}

# Multiple variables
connection: postgresql://${DB_USER}:${DB_PASS}@${DB_HOST}/${DB_NAME}
```

### Required Variables

| Variable | Used In | Description |
|----------|---------|-------------|
| `DATABASE_URL` | sources[].connection | Database connection string |
| `SLACK_WEBHOOK_URL` | alerting.webhooks[].url | Slack incoming webhook |
| `WEBHOOK_SECRET` | alerting.webhooks[].secret | HMAC signing key |

## Source Configuration

### Dialect-Specific Connection Strings

**PostgreSQL:**
```yaml
dialect: postgres
connection: postgresql://user:pass@host:5432/database
# or
connection: ${DATABASE_URL}
```

**MySQL:**
```yaml
dialect: mysql
connection: mysql://user:pass@host:3306/database
```

**ClickHouse:**
```yaml
dialect: clickhouse
connection: clickhouse://user:pass@host:8123/database
```

**SQLite:**
```yaml
dialect: sqlite
connection: /path/to/database.db
# or
connection: sqlite:///path/to/database.db
```

### Query Requirements

Your query MUST return:

| Column | Type | Required | Description |
|--------|------|----------|-------------|
| `row_count` | INTEGER | **Yes** | Number of rows |
| `latest_timestamp` | TIMESTAMP | No | Most recent data point |

Example queries:

```sql
-- Minimal (volume only)
SELECT COUNT(*) as row_count FROM orders

-- Full (volume + freshness)
SELECT 
    COUNT(*) as row_count,
    MAX(created_at) as latest_timestamp
FROM orders
WHERE created_at >= NOW() - INTERVAL '24 hours'

-- With additional metrics (ignored but allowed)
SELECT 
    COUNT(*) as row_count,
    MAX(created_at) as latest_timestamp,
    AVG(amount) as avg_amount  -- ignored
FROM orders
```

### Schedule Syntax

Uses standard cron syntax: `minute hour day month weekday`

```yaml
schedule: "0 * * * *"       # Every hour at :00
schedule: "*/15 * * * *"    # Every 15 minutes
schedule: "0 9 * * 1-5"     # 9 AM weekdays
schedule: "0 0 1 * *"       # First day of month
```

### Detection Thresholds

**Freshness:**

```yaml
freshness:
  max_age_hours: 24    # Hard limit (optional)
  factor: 2.0          # Baseline × factor = dynamic limit
```

- If `latest_timestamp` age > `max_age_hours` → ANOMALY
- If `latest_timestamp` age > baseline_interval × `factor` → WARNING

**Volume:**

```yaml
volume:
  min_row_count: 100      # Hard minimum (optional)
  deviation_factor: 3.0   # stddev × factor = deviation limit
```

- If `row_count` < `min_row_count` → ANOMALY
- If `row_count` deviates > `deviation_factor` × stddev → WARNING

## Alerting Configuration

### Event Types

| Event | When Triggered |
|-------|----------------|
| `anomaly` | Status changed to ANOMALY |
| `warning` | Status changed to WARNING |
| `recovery` | Status returned to OK after anomaly/warning |
| `info` | Test payloads, informational messages |

### Cooldown

```yaml
alerting:
  cooldown_minutes: 60
```

Prevents alert spam. After sending an alert, won't send another for the same source + target + status within the cooldown window.

### HMAC Signing

If `secret` is provided, payload is signed:

```yaml
webhooks:
  - name: secure-endpoint
    url: ${WEBHOOK_URL}
    secret: ${WEBHOOK_SECRET}
```

Signature header: `X-DataFold-Signature: sha256=<hex_digest>`

Verification (Python):
```python
import hmac
import hashlib

def verify(payload: bytes, signature: str, secret: str) -> bool:
    expected = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(f"sha256={expected}", signature)
```

## Retention Configuration

```yaml
retention:
  days: 30           # Delete snapshots older than 30 days
  min_snapshots: 10  # But always keep at least 10 per source
```

Run cleanup manually:
```bash
datafold purge --dry-run  # Preview
datafold purge            # Execute
```

## Baseline Configuration

```yaml
baseline:
  window_size: 20      # Use last 20 successful snapshots
  max_age_days: 30     # Ignore snapshots older than 30 days
```

Larger `window_size` = more stable baselines, slower to adapt
Smaller `window_size` = faster adaptation, more sensitive

## Validation

Validate your configuration:

```bash
datafold validate
```

Common validation errors:

| Error | Cause | Fix |
|-------|-------|-----|
| `Hardcoded password detected` | Password in connection string | Use `${ENV_VAR}` |
| `Invalid cron expression` | Malformed schedule | Check cron syntax |
| `Unknown dialect` | Unsupported database | Use postgres/mysql/clickhouse/sqlite |
| `Missing environment variable` | Env var not set | Export the variable |

## Example Configurations

### Minimal

```yaml
version: "1"

sources:
  - name: orders
    type: sql
    dialect: postgres
    connection: ${DATABASE_URL}
    query: "SELECT COUNT(*) as row_count FROM orders"
    schedule: "0 * * * *"

alerting:
  webhooks:
    - name: slack
      url: ${SLACK_URL}
      events: [anomaly]
```

### Production

See [examples/datafold.yaml](../examples/datafold.yaml) for a complete production configuration.
