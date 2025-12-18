# Troubleshooting

Common issues and solutions.

## Configuration Issues

### "Hardcoded password detected"

**Error:**
```
ValidationError: Hardcoded password detected in connection string
```

**Cause:** Connection string contains password directly.

**Fix:** Use environment variables:
```yaml
# ❌ Wrong
connection: postgresql://user:password@host/db

# ✅ Correct
connection: ${DATABASE_URL}
```

### "Missing environment variable"

**Error:**
```
ConfigError: Environment variable DATABASE_URL is not set
```

**Cause:** Required env var not exported.

**Fix:**
```bash
export DATABASE_URL="postgresql://user:pass@host:5432/db"
datafold check
```

Or in Docker:
```bash
docker run -e DATABASE_URL="..." ...
```

### "Invalid cron expression"

**Error:**
```
ValidationError: Invalid cron expression: "every 5 minutes"
```

**Cause:** Human-readable schedule instead of cron syntax.

**Fix:**
```yaml
# ❌ Wrong
schedule: "every 5 minutes"

# ✅ Correct
schedule: "*/5 * * * *"
```

## Connection Issues

### "Connection refused"

**Error:**
```
ConnectionError: Database connection failed: connection refused
```

**Causes:**
1. Database not running
2. Wrong host/port
3. Firewall blocking connection
4. Docker networking issue

**Fixes:**

Check database is running:
```bash
pg_isready -h localhost -p 5432
```

In Docker, use service name:
```yaml
# docker-compose.yaml
connection: postgresql://user:pass@postgres:5432/db  # Not localhost!
```

### "Authentication failed"

**Error:**
```
ConnectionError: FATAL: password authentication failed
```

**Cause:** Wrong credentials.

**Fix:** Verify credentials:
```bash
psql $DATABASE_URL -c "SELECT 1"
```

### "SSL required"

**Error:**
```
ConnectionError: SSL connection is required
```

**Fix:** Add SSL params:
```yaml
connection: ${DATABASE_URL}?sslmode=require
```

### "Timeout"

**Error:**
```
ConnectionError: Query timeout after 30 seconds
```

**Causes:**
1. Slow query
2. Network latency
3. Database overloaded

**Fixes:**

Increase timeout:
```yaml
sources:
  - name: slow_query
    timeout_seconds: 120  # Default is 30
```

Optimize query:
```sql
-- Add indexes, reduce scan range
SELECT COUNT(*) as row_count
FROM orders
WHERE created_at >= NOW() - INTERVAL '1 day'  -- Use indexed column
```

## Query Issues

### "Column row_count not found"

**Error:**
```
QueryError: Required column 'row_count' not found in result
```

**Cause:** Query doesn't return `row_count` column.

**Fix:**
```sql
-- ❌ Wrong
SELECT COUNT(*) FROM orders

-- ✅ Correct
SELECT COUNT(*) as row_count FROM orders
```

### "Invalid timestamp format"

**Error:**
```
QueryError: Cannot parse latest_timestamp: invalid format
```

**Cause:** Timestamp in unexpected format.

**Fix:** Ensure standard ISO format:
```sql
-- PostgreSQL
SELECT MAX(created_at) as latest_timestamp FROM orders

-- MySQL (if using non-standard format)
SELECT DATE_FORMAT(MAX(created_at), '%Y-%m-%dT%H:%i:%s') as latest_timestamp
```

### "Zero rows returned"

This is detected as an anomaly, not an error. If expected:

```yaml
volume:
  min_row_count: 0  # Allow zero rows
```

## Alert Issues

### "Webhook not receiving alerts"

**Causes:**
1. Wrong event type configured
2. Cooldown active
3. Status hasn't changed
4. Network/firewall issue

**Debug steps:**

1. Check events config:
   ```yaml
   events: [anomaly, recovery]  # Is your event type included?
   ```

2. Test webhook directly:
   ```bash
   datafold test-webhook --target slack
   ```

3. Check cooldown:
   ```bash
   datafold status  # Shows last alert times
   ```

4. Check delivery log:
   ```bash
   sqlite3 datafold.db "SELECT * FROM delivery_log ORDER BY delivered_at DESC LIMIT 5"
   ```

### "Signature verification failed"

**Cause:** Secret mismatch or payload modification.

**Fixes:**

1. Verify secret matches:
   ```bash
   echo $WEBHOOK_SECRET  # Should match receiver
   ```

2. Use raw request body:
   ```python
   # ❌ Wrong - parsed JSON
   body = request.json
   
   # ✅ Correct - raw bytes
   body = request.data
   ```

3. Check encoding:
   ```python
   # Ensure UTF-8
   body = request.data.decode('utf-8')
   ```

### "Too many alerts"

**Cause:** Cooldown too short or flapping status.

**Fixes:**

1. Increase cooldown:
   ```yaml
   alerting:
     cooldown_minutes: 120  # Was 60
   ```

2. Increase deviation tolerance:
   ```yaml
   volume:
     deviation_factor: 4.0  # Was 3.0
   ```

### "Missing alerts"

**Cause:** Cooldown blocking, or status didn't change.

**Fix:** Alerts only fire on status CHANGE. Same status = no alert.

To force re-alert, clear state:
```bash
sqlite3 datafold.db "DELETE FROM alert_states WHERE source_name = 'my_source'"
```

## Storage Issues

### "Database is locked"

**Error:**
```
sqlite3.OperationalError: database is locked
```

**Cause:** Multiple processes accessing SQLite.

**Fixes:**

1. Use single instance only
2. Increase timeout (internal)
3. Use Postgres backend (future feature)

### "Disk full"

**Error:**
```
sqlite3.OperationalError: disk I/O error
```

**Fixes:**

1. Run purge:
   ```bash
   datafold purge
   ```

2. Reduce retention:
   ```yaml
   retention:
     days: 7  # Was 30
   ```

3. Move to larger volume

### "Corrupt database"

**Symptoms:** Random errors, missing data.

**Fix:**
```bash
# Backup
cp datafold.db datafold.db.bak

# Check integrity
sqlite3 datafold.db "PRAGMA integrity_check"

# If corrupt, recover:
sqlite3 datafold.db ".dump" | sqlite3 datafold_new.db
mv datafold_new.db datafold.db
```

## Runtime Issues

### "No such command"

**Error:**
```
Error: No such command 'cheek'
```

**Fix:** Check spelling:
```bash
datafold --help  # List all commands
```

### "Permission denied"

**Error:**
```
PermissionError: [Errno 13] Permission denied: './datafold.db'
```

**Cause:** Wrong file permissions.

**Fixes:**

```bash
# Check permissions
ls -la datafold.db

# Fix ownership
chown $(whoami) datafold.db

# In Docker, use correct user
docker run --user $(id -u):$(id -g) ...
```

### "Memory error"

**Cause:** Query returning too much data.

**Fix:** Add LIMIT to query:
```sql
SELECT COUNT(*) as row_count,
       MAX(created_at) as latest_timestamp
FROM orders
WHERE created_at >= NOW() - INTERVAL '1 day'
LIMIT 1  -- Ensure single row
```

## Docker Issues

### "Config file not found"

**Error:**
```
ConfigError: Config file not found: /app/datafold.yaml
```

**Fix:** Mount config correctly:
```bash
docker run -v $(pwd)/datafold.yaml:/app/datafold.yaml:ro ...
```

### "Volume permissions"

**Error:**
```
PermissionError: /app/data/datafold.db
```

**Fix:** Create volume with correct permissions:
```bash
docker volume create datafold-data

# Or fix existing
docker run -v datafold-data:/app/data \
  --entrypoint /bin/sh \
  ghcr.io/datafold/agent:latest \
  -c "chown -R datafold:datafold /app/data"
```

### "Network unreachable"

**Error:**
```
ConnectionError: Network is unreachable
```

**Fix:** Check Docker network:
```bash
# Use host network for database access
docker run --network host ...

# Or use Docker network
docker network create datafold-net
```

## Getting Help

### Collect Debug Info

```bash
# Version
datafold --version

# Config (masked)
datafold render-config

# Status
datafold status --json

# Recent history
datafold history <source> --limit 10 --json

# Check verbose
datafold check --force --verbose 2>&1
```

### Log Levels

```yaml
agent:
  log_level: debug  # debug, info, warn, error
```

### Database Inspection

```bash
# All tables
sqlite3 datafold.db ".tables"

# Recent snapshots
sqlite3 datafold.db "SELECT * FROM snapshots ORDER BY collected_at DESC LIMIT 5"

# Alert states
sqlite3 datafold.db "SELECT * FROM alert_states"

# Failed deliveries
sqlite3 datafold.db "SELECT * FROM delivery_log WHERE success = 0"
```
