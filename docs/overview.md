# Overview

## What is DataFold?

DataFold is an open-source CLI agent that monitors your SQL data sources and automatically detects data quality issues:

- **Freshness problems** - data stopped updating
- **Volume anomalies** - unexpected drops or spikes in row counts
- **Silent failures** - ETL succeeded but data is semantically broken

## The Problem

Your data pipeline can fail in ways that don't trigger errors:

```
✅ Airflow DAG: SUCCESS
✅ dbt run: PASSED  
✅ Row count: 1,247 rows
❌ Reality: All rows are from yesterday (stale data)
```

Traditional monitoring checks if jobs run. DataFold checks if data is actually healthy.

## Key Features

| Feature | Description |
|---------|-------------|
| **Freshness Detection** | Alerts when `latest_timestamp` stops advancing |
| **Volume Monitoring** | Catches drops, spikes, and empty tables |
| **Baseline Learning** | No manual thresholds - learns from your data patterns |
| **Webhook Alerts** | Slack, PagerDuty, or any HTTP endpoint |
| **CLI-First** | DevOps-friendly, scriptable, no UI required |
| **Lightweight** | Single process, SQLite storage, minimal dependencies |

## How It Works

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│   Data Source   │────▶│  DataFold Agent  │────▶│  Webhook Alert  │
│  (PostgreSQL)   │     │                  │     │    (Slack)      │
└─────────────────┘     └──────────────────┘     └─────────────────┘
                               │
                               ▼
                        ┌──────────────────┐
                        │  SQLite State    │
                        │  (baselines,     │
                        │   history)       │
                        └──────────────────┘
```

1. **Collect** - Run your SQL query against the data source
2. **Analyze** - Compare current metrics to learned baseline
3. **Decide** - Determine if this is OK, WARNING, or ANOMALY
4. **Alert** - Send webhook if status changed

## Detection Types

### Freshness Detection

Monitors the `latest_timestamp` returned by your query:

```sql
SELECT MAX(created_at) as latest_timestamp FROM orders
```

Triggers alert when:
- Data is older than `max_age_hours` (hard limit)
- Data age exceeds baseline × `factor` (learned threshold)

### Volume Detection

Monitors the `row_count` returned by your query:

```sql
SELECT COUNT(*) as row_count FROM orders WHERE created_at > NOW() - INTERVAL '1 day'
```

Triggers alert when:
- Count drops below `min_row_count` (hard minimum)
- Count deviates by more than `deviation_factor` × stddev from baseline

## Query Contract

Your SQL query MUST return these columns:

| Column | Type | Required | Description |
|--------|------|----------|-------------|
| `row_count` | INTEGER | Yes | Number of rows (COUNT) |
| `latest_timestamp` | TIMESTAMP | No | Most recent data timestamp |

Example:
```sql
SELECT 
    COUNT(*) as row_count,
    MAX(updated_at) as latest_timestamp
FROM my_table
WHERE updated_at >= NOW() - INTERVAL '24 hours'
```

## Supported Databases

| Database | Dialect | Driver |
|----------|---------|--------|
| PostgreSQL | `postgres` | psycopg2 |
| MySQL | `mysql` | pymysql |
| ClickHouse | `clickhouse` | clickhouse-driver |
| SQLite | `sqlite` | built-in |

## Use Cases

### Analytics Dashboard Monitoring

```yaml
sources:
  - name: dashboard_metrics
    query: |
      SELECT COUNT(*) as row_count, MAX(calculated_at) as latest_timestamp
      FROM analytics.daily_metrics
      WHERE date = CURRENT_DATE
    schedule: "0 9 * * *"  # Check at 9 AM
    freshness:
      max_age_hours: 24
```

### E-commerce Order Pipeline

```yaml
sources:
  - name: orders_hourly
    query: |
      SELECT COUNT(*) as row_count, MAX(created_at) as latest_timestamp  
      FROM orders
      WHERE created_at >= NOW() - INTERVAL '1 hour'
    schedule: "5 * * * *"  # Every hour at :05
    volume:
      min_row_count: 100  # Expect at least 100 orders/hour
```

### Event Stream Health

```yaml
sources:
  - name: events_stream
    query: |
      SELECT count() as row_count, max(timestamp) as latest_timestamp
      FROM events
      WHERE timestamp >= now() - INTERVAL 15 MINUTE
    schedule: "*/5 * * * *"  # Every 5 minutes
    freshness:
      max_age_hours: 0.5  # 30 minutes max staleness
```

## What DataFold Is NOT

- **Not a data quality rules engine** - No custom SQL assertions
- **Not a data catalog** - No metadata management
- **Not a lineage tracker** - No dependency mapping
- **Not dbt tests** - Focused on behavioral patterns, not schema validation

DataFold is a **behavioral anomaly detector** that learns what "normal" looks like and alerts when reality deviates.
