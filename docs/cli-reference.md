# CLI Reference

Complete reference for all DriftGuard commands.

## Global Options

```bash
driftguard [OPTIONS] COMMAND [ARGS]
```

| Option | Description |
|--------|-------------|
| `--version` | Show version and exit |
| `-c, --config PATH` | Path to config file |
| `-v, --verbose` | Enable verbose output |
| `-q, --quiet` | Suppress non-essential output |
| `--json` | Output in JSON format |
| `--help` | Show help and exit |

## Commands

### `init`

Create a new configuration file.

```bash
driftguard init [OPTIONS]
```

| Option | Description |
|--------|-------------|
| `--path PATH` | Output path (default: `./driftguard.yaml`) |
| `--force` | Overwrite existing file |

**Example:**
```bash
driftguard init --path /etc/driftguard/config.yaml
```

---

### `validate`

Validate configuration file.

```bash
driftguard validate [OPTIONS]
```

| Option | Description |
|--------|-------------|
| `--strict` | Fail on warnings |

**Example:**
```bash
driftguard validate
# Output:
# ✓ Configuration is valid
#   Sources: 3
#   Webhooks: 2
```

**Exit codes:**
- `0` - Valid
- `1` - Invalid

---

### `render-config`

Show resolved configuration with environment variables expanded and secrets masked.

```bash
driftguard render-config
```

**Example:**
```bash
driftguard render-config
# Output:
# sources:
#   - name: orders
#     connection: postgresql://user:***@host/db
```

---

### `check`

Run checks on data sources.

```bash
driftguard check [OPTIONS]
```

| Option | Description |
|--------|-------------|
| `--source NAME` | Check specific source only |
| `--force` | Run regardless of schedule |
| `--dry-run` | Don't send alerts or save state |

**Examples:**
```bash
# Check all sources (respects schedule)
driftguard check

# Force check all sources
driftguard check --force

# Check specific source
driftguard check --source orders --force

# Preview without side effects
driftguard check --force --dry-run
```

**Output:**
```
Checked 2 source(s)

orders  OK
  Row count: 1,247
  Latest data: 2024-01-15T10:30:00Z
  Duration: 45ms

users  ANOMALY
  Row count: 0
  Duration: 12ms
  → Row count 0 is below minimum threshold of 100
  ✓ Sent to slack

Summary: 1 OK, 1 ANOMALY
```

**Exit codes:**
- `0` - All OK
- `1` - Error (config, connection, etc.)
- `2` - Anomaly detected

---

### `run`

Start daemon mode with internal scheduler.

```bash
driftguard run [OPTIONS]
```

| Option | Description |
|--------|-------------|
| `--once` | Run one cycle and exit |

**Example:**
```bash
# Continuous daemon
driftguard run

# Single cycle (useful for external schedulers)
driftguard run --once
```

**Behavior:**
- Runs checks according to each source's cron schedule
- Sends alerts on status changes
- Handles SIGINT/SIGTERM gracefully

---

### `status`

Show current status of all sources.

```bash
driftguard status [OPTIONS]
```

| Option | Description |
|--------|-------------|
| `--json` | Output as JSON |

**Example:**
```bash
driftguard status
```

**Output:**
```
┏━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━━━┳━━━━━━━━━┓
┃ Source ┃ Last Check           ┃ Status  ┃ Row Count ┃ Enabled ┃
┡━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━━━╇━━━━━━━━━┩
│ orders │ 2024-01-15T10:30:00Z │ SUCCESS │ 1,247     │ Yes     │
│ users  │ 2024-01-15T10:30:05Z │ SUCCESS │ 892       │ Yes     │
│ events │ -                    │ NEVER   │ -         │ No      │
└────────┴──────────────────────┴─────────┴───────────┴─────────┘
```

---

### `history`

Show snapshot history for a source.

```bash
driftguard history SOURCE [OPTIONS]
```

| Argument | Description |
|----------|-------------|
| `SOURCE` | Source name |

| Option | Description |
|--------|-------------|
| `--limit N` | Number of snapshots (default: 20) |
| `--json` | Output as JSON |

**Example:**
```bash
driftguard history orders --limit 5
```

**Output:**
```
                  History: orders
┏━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━┓
┃ Time                ┃ Status  ┃ Row Count ┃ Latest Data      ┃
┡━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━┩
│ 2024-01-15 10:30:00 │ SUCCESS │ 1,247     │ 2024-01-15 10:28 │
│ 2024-01-15 04:30:00 │ SUCCESS │ 1,198     │ 2024-01-15 04:27 │
│ 2024-01-14 22:30:00 │ SUCCESS │ 1,312     │ 2024-01-14 22:29 │
│ 2024-01-14 16:30:00 │ SUCCESS │ 1,089     │ 2024-01-14 16:25 │
│ 2024-01-14 10:30:00 │ SUCCESS │ 1,156     │ 2024-01-14 10:28 │
└─────────────────────┴─────────┴───────────┴──────────────────┘
```

---

### `explain`

Explain baseline and detection thresholds for a source.

```bash
driftguard explain --source SOURCE [OPTIONS]
```

| Option | Description |
|--------|-------------|
| `--source NAME` | Source name (required) |
| `--json` | Output as JSON |

**Example:**
```bash
driftguard explain --source orders
```

**Output:**
```
Source: orders

Configuration:
  Schedule: 0 */6 * * *
  Freshness max age: 8.0h
  Volume min: 100
  Deviation factor: 3.0

Baseline (from 20 snapshots):
  Row count median: 1,200
  Row count range: 1,050 - 1,350
  Row count stddev: 85.3
  Expected interval: 6.0h

Snapshots in baseline:
  2024-01-15 10:30 - 1,247 rows
  2024-01-15 04:30 - 1,198 rows
  2024-01-14 22:30 - 1,312 rows
  2024-01-14 16:30 - 1,089 rows
  2024-01-14 10:30 - 1,156 rows
  ... and 15 more
```

---

### `test-webhook`

Send a test webhook payload.

```bash
driftguard test-webhook [OPTIONS]
```

| Option | Description |
|--------|-------------|
| `--target NAME` | Specific webhook target |

**Example:**
```bash
driftguard test-webhook --target slack
```

**Output:**
```
Testing webhook: slack
  URL: https://hooks.slack.com/services/***
  ✓ Delivered successfully (245ms)
```

---

### `migrate`

Apply storage migrations.

```bash
driftguard migrate
```

Run after upgrading DriftGuard to apply schema changes.

---

### `purge`

Clean up old snapshots according to retention policy.

```bash
driftguard purge [OPTIONS]
```

| Option | Description |
|--------|-------------|
| `--dry-run` | Preview without deleting |

**Example:**
```bash
# Preview
driftguard purge --dry-run
# Output:
# Would delete 127 snapshots older than 30 days
# Would keep 10 minimum per source

# Execute
driftguard purge
# Output:
# Deleted 127 snapshots
```

---

## JSON Output

All commands support `--json` for machine-readable output:

```bash
driftguard status --json
```

```json
[
  {
    "source": "orders",
    "last_check": "2024-01-15T10:30:00Z",
    "status": "SUCCESS",
    "row_count": 1247,
    "enabled": true
  }
]
```

```bash
driftguard check --force --json
```

```json
{
  "results": [
    {
      "source": "orders",
      "status": "OK",
      "metrics": {
        "row_count": 1247,
        "latest_timestamp": "2024-01-15T10:28:00Z"
      },
      "reasons": [],
      "alerts": {},
      "duration_ms": 45
    }
  ]
}
```

## Exit Codes

| Code | Meaning |
|------|---------|
| `0` | Success / All OK |
| `1` | Error (config, connection, runtime) |
| `2` | Anomaly or warning detected |

Use in scripts:
```bash
driftguard check --force
if [ $? -eq 2 ]; then
    echo "Anomaly detected!"
fi
```
