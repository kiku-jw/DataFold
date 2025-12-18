# Detection Logic

How DataFold detects anomalies in your data.

## Overview

DataFold uses a **behavioral baseline approach**:

1. Collect metrics from your data source
2. Compare to historical baseline (learned from past snapshots)
3. Apply threshold rules (both hard limits and statistical)
4. Make a decision: OK, WARNING, or ANOMALY

## Decision Status

| Status | Meaning | Exit Code |
|--------|---------|-----------|
| `OK` | Everything normal | 0 |
| `WARNING` | Deviation detected, may need attention | 2 |
| `ANOMALY` | Critical issue, requires action | 2 |

## Detection Types

### 1. Collection Failure

If the SQL query fails (connection error, timeout, syntax error):

```
Status: ANOMALY
Reason: COLLECT_FAILED - Database connection failed: ...
```

### 2. Freshness Detection

Monitors how old the most recent data is.

**Inputs:**
- `latest_timestamp` from your query
- `freshness.max_age_hours` from config
- `freshness.factor` from config (default: 2.0)
- Baseline expected interval (learned)

**Logic:**

```python
data_age = now - latest_timestamp

# Hard limit (if configured)
if max_age_hours and data_age > max_age_hours:
    return ANOMALY, "Data is stale"

# Baseline comparison (if baseline exists)
if baseline.expected_interval:
    threshold = baseline.expected_interval * factor
    if data_age > threshold:
        return WARNING, "No new data since ..."
```

**Example:**

```yaml
freshness:
  max_age_hours: 8    # Hard limit
  factor: 2.0         # Baseline multiplier
```

If baseline interval is 6 hours and `factor=2.0`:
- Data age 5h → OK (within baseline)
- Data age 10h → WARNING (exceeds 6h × 2.0 = 12h... wait, 10 < 12, so OK)
- Data age 14h → WARNING (exceeds 12h)
- Data age 9h → ANOMALY (exceeds hard limit of 8h)

### 3. Volume Detection

Monitors the row count returned by your query.

**Inputs:**
- `row_count` from your query
- `volume.min_row_count` from config
- `volume.deviation_factor` from config (default: 3.0)
- Baseline statistics (median, stddev)

**Logic:**

```python
# Zero rows is always an anomaly
if row_count == 0:
    return ANOMALY, "Zero rows returned"

# Hard minimum (if configured)
if min_row_count and row_count < min_row_count:
    return ANOMALY, f"Row count {row_count} is below minimum {min_row_count}"

# Baseline comparison (if baseline exists with stddev)
if baseline.row_count_median and baseline.row_count_stddev:
    deviation = abs(row_count - baseline.row_count_median)
    threshold = baseline.row_count_stddev * deviation_factor
    
    if deviation > threshold:
        direction = "above" if row_count > median else "below"
        return WARNING, f"Row count deviates {direction} baseline"
```

**Example:**

```yaml
volume:
  min_row_count: 100    # Hard minimum
  deviation_factor: 3.0  # Stddev multiplier
```

If baseline is:
- Median: 1,000 rows
- Stddev: 100 rows
- `deviation_factor`: 3.0

Then threshold = 100 × 3.0 = 300 rows deviation allowed.

| Row Count | Decision | Reason |
|-----------|----------|--------|
| 1,050 | OK | Within baseline |
| 750 | WARNING | 250 below median (within 3σ) |
| 500 | WARNING | 500 below median (exceeds 3σ) |
| 50 | ANOMALY | Below min_row_count (100) |
| 0 | ANOMALY | Zero rows |

## Baseline Calculation

The baseline is calculated from historical successful snapshots.

### Parameters

```yaml
baseline:
  window_size: 20      # Use last N snapshots
  max_age_days: 30     # Ignore snapshots older than N days
```

### Statistics Calculated

| Statistic | Description | Used For |
|-----------|-------------|----------|
| `row_count_median` | Median row count | Central tendency |
| `row_count_min` | Minimum row count | Range check |
| `row_count_max` | Maximum row count | Range check |
| `row_count_stddev` | Standard deviation | Deviation threshold |
| `expected_interval_seconds` | Median time between snapshots | Freshness baseline |
| `snapshot_count` | Number of snapshots in baseline | Confidence |

### Confidence Score

Confidence increases with more baseline data:

```python
if snapshot_count >= 10:
    confidence = 1.0  # Full confidence
elif snapshot_count >= 5:
    confidence = 0.8
elif snapshot_count >= 3:
    confidence = 0.5
else:
    confidence = 0.3  # Low confidence, rely on hard limits
```

With low confidence, DataFold relies more on configured hard limits (`max_age_hours`, `min_row_count`).

## Decision Priority

Checks are evaluated in order:

1. **Collection failure** → ANOMALY (immediate)
2. **Zero rows** → ANOMALY (immediate)
3. **Below min_row_count** → ANOMALY
4. **Exceeds max_age_hours** → ANOMALY
5. **Volume deviation** → WARNING
6. **Freshness deviation** → WARNING
7. **All checks pass** → OK

Multiple reasons can be reported:

```
orders  ANOMALY
  → Data is stale (last update: 2024-01-14)
  → Row count 50 is below minimum threshold of 100
```

## Alerting Integration

When status changes, alerts are triggered:

| Previous | Current | Alert Event |
|----------|---------|-------------|
| OK | WARNING | `warning` |
| OK | ANOMALY | `anomaly` |
| WARNING | ANOMALY | `anomaly` |
| WARNING | OK | `recovery` |
| ANOMALY | OK | `recovery` |
| ANOMALY | WARNING | (no alert, still degraded) |

### Deduplication

Alerts are deduplicated by:
- Source name
- Target (webhook name)
- Status
- Reason hash (hash of reason codes)

If the same alert would be sent again, it's suppressed.

### Cooldown

After sending an alert, no alerts for the same source + target within `cooldown_minutes`:

```yaml
alerting:
  cooldown_minutes: 60
```

## Tuning Recommendations

### Too Many False Positives?

1. Increase `deviation_factor`:
   ```yaml
   volume:
     deviation_factor: 4.0  # More tolerant (was 3.0)
   ```

2. Increase baseline `window_size`:
   ```yaml
   baseline:
     window_size: 50  # More history (was 20)
   ```

3. Remove hard limits if too strict:
   ```yaml
   volume:
     # min_row_count: 100  # Removed
   ```

### Missing Real Anomalies?

1. Decrease `deviation_factor`:
   ```yaml
   volume:
     deviation_factor: 2.0  # More sensitive (was 3.0)
   ```

2. Add hard limits as safety net:
   ```yaml
   freshness:
     max_age_hours: 24  # Never allow data older than 24h
   volume:
     min_row_count: 100  # Never allow below 100 rows
   ```

3. Decrease `cooldown_minutes` for faster repeat alerts:
   ```yaml
   alerting:
     cooldown_minutes: 15  # Was 60
   ```

## Viewing Detection State

```bash
# See current baseline
datafold explain --source orders

# See detection history
datafold history orders --limit 50
```
