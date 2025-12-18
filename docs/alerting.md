# Alerting

Configure webhooks and understand alert payloads.

## Webhook Configuration

```yaml
alerting:
  cooldown_minutes: 60
  
  webhooks:
    - name: slack
      url: ${SLACK_WEBHOOK_URL}
      secret: ${WEBHOOK_SECRET}
      events: [anomaly, recovery]
      timeout_seconds: 10
```

### Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `name` | string | required | Unique identifier |
| `url` | string | required | Webhook URL (use env var) |
| `secret` | string | optional | HMAC signing secret |
| `events` | list | all | Event types to send |
| `timeout_seconds` | int | 10 | Request timeout |

### Event Types

| Event | Triggered When |
|-------|----------------|
| `anomaly` | Status changed to ANOMALY |
| `warning` | Status changed to WARNING |
| `recovery` | Status returned to OK |
| `info` | Test payloads only |

## Payload Format

All webhooks receive JSON payloads:

```json
{
  "version": "1",
  "event_id": "550e8400-e29b-41d4-a716-446655440000",
  "event_type": "anomaly",
  "timestamp": "2024-01-15T10:30:00Z",
  "source": {
    "name": "orders_daily",
    "type": "sql"
  },
  "decision": {
    "status": "ANOMALY",
    "reasons": [
      {
        "code": "VOLUME_BELOW_MINIMUM",
        "message": "Row count 50 is below minimum threshold of 100",
        "severity": "critical"
      },
      {
        "code": "DATA_STALE",
        "message": "No new data since 2024-01-14T22:00:00Z",
        "severity": "warning"
      }
    ],
    "confidence": 0.95
  },
  "metrics": {
    "row_count": 50,
    "latest_timestamp": "2024-01-14T22:00:00Z"
  },
  "baseline": {
    "snapshot_count": 20,
    "row_count_median": 1200,
    "row_count_min": 1050,
    "row_count_max": 1350,
    "row_count_stddev": 85.3,
    "expected_interval_seconds": 21600
  },
  "context": {
    "agent_id": "prod-datafold-agent"
  }
}
```

### Payload Fields

| Field | Description |
|-------|-------------|
| `version` | Payload schema version |
| `event_id` | Unique event identifier (UUID) |
| `event_type` | `anomaly`, `warning`, `recovery`, `info` |
| `timestamp` | When the alert was generated |
| `source.name` | Data source name |
| `source.type` | Source type (e.g., `sql`) |
| `decision.status` | `OK`, `WARNING`, `ANOMALY` |
| `decision.reasons` | List of detection reasons |
| `decision.confidence` | Baseline confidence (0-1) |
| `metrics` | Current snapshot metrics |
| `baseline` | Baseline statistics |
| `context.agent_id` | Agent identifier |

### Reason Codes

| Code | Severity | Description |
|------|----------|-------------|
| `COLLECT_FAILED` | critical | Query failed |
| `VOLUME_ZERO` | critical | Zero rows returned |
| `VOLUME_BELOW_MINIMUM` | critical | Below min_row_count |
| `VOLUME_DEVIATION` | warning | Exceeds deviation threshold |
| `DATA_STALE` | warning/critical | Data age exceeded |

## HMAC Signature

When `secret` is configured, payloads are signed:

### Request Headers

```http
POST /webhook HTTP/1.1
Content-Type: application/json
X-DataFold-Signature: sha256=abc123...
X-DataFold-Event: anomaly
X-DataFold-Source: orders_daily
```

### Signature Verification

The signature is HMAC-SHA256 of the raw JSON payload:

**Python:**
```python
import hmac
import hashlib

def verify_signature(payload: bytes, signature: str, secret: str) -> bool:
    expected = hmac.new(
        secret.encode(),
        payload,
        hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(f"sha256={expected}", signature)

# Usage
raw_body = request.data  # Raw bytes
signature = request.headers.get("X-DataFold-Signature")
secret = os.environ["WEBHOOK_SECRET"]

if not verify_signature(raw_body, signature, secret):
    return "Invalid signature", 401
```

**Node.js:**
```javascript
const crypto = require('crypto');

function verifySignature(payload, signature, secret) {
  const expected = 'sha256=' + crypto
    .createHmac('sha256', secret)
    .update(payload)
    .digest('hex');
  return crypto.timingSafeEqual(
    Buffer.from(expected),
    Buffer.from(signature)
  );
}
```

## Slack Integration

### Incoming Webhook

1. Create Slack app at https://api.slack.com/apps
2. Enable "Incoming Webhooks"
3. Add webhook to channel
4. Copy webhook URL

```yaml
webhooks:
  - name: slack
    url: ${SLACK_WEBHOOK_URL}
    events: [anomaly, recovery]
```

### Custom Slack Formatting

DataFold sends raw JSON. For formatted Slack messages, use a middleware:

```python
# Example: Flask middleware that converts to Slack format
@app.route('/datafold-to-slack', methods=['POST'])
def datafold_to_slack():
    data = request.json
    
    color = {
        'anomaly': 'danger',
        'warning': 'warning', 
        'recovery': 'good'
    }.get(data['event_type'], '#666666')
    
    slack_payload = {
        "attachments": [{
            "color": color,
            "title": f"DataFold: {data['source']['name']}",
            "text": f"Status: {data['decision']['status']}",
            "fields": [
                {"title": "Row Count", "value": data['metrics']['row_count'], "short": True},
                {"title": "Event", "value": data['event_type'], "short": True}
            ],
            "footer": f"Agent: {data['context']['agent_id']}",
            "ts": int(datetime.fromisoformat(data['timestamp'].replace('Z', '+00:00')).timestamp())
        }]
    }
    
    requests.post(os.environ['SLACK_WEBHOOK_URL'], json=slack_payload)
    return "OK"
```

## PagerDuty Integration

### Events API v2

```yaml
webhooks:
  - name: pagerduty
    url: https://events.pagerduty.com/v2/enqueue
    events: [anomaly]
```

Use a middleware to convert to PagerDuty format:

```python
@app.route('/datafold-to-pagerduty', methods=['POST'])
def datafold_to_pagerduty():
    data = request.json
    
    if data['event_type'] == 'recovery':
        event_action = 'resolve'
    else:
        event_action = 'trigger'
    
    pd_payload = {
        "routing_key": os.environ['PAGERDUTY_ROUTING_KEY'],
        "event_action": event_action,
        "dedup_key": f"datafold-{data['source']['name']}",
        "payload": {
            "summary": f"DataFold: {data['decision']['status']} on {data['source']['name']}",
            "severity": "critical" if data['event_type'] == 'anomaly' else "warning",
            "source": data['context']['agent_id'],
            "custom_details": {
                "metrics": data['metrics'],
                "reasons": [r['message'] for r in data['decision']['reasons']]
            }
        }
    }
    
    requests.post(
        'https://events.pagerduty.com/v2/enqueue',
        json=pd_payload
    )
    return "OK"
```

## Retry Behavior

Failed webhook deliveries are retried:

| Attempt | Delay |
|---------|-------|
| 1 | Immediate |
| 2 | 1 second |
| 3 | 5 seconds |
| 4 | 15 seconds |

After 4 attempts, the delivery is marked as failed.

### Failure Logging

Failed deliveries are logged in SQLite:

```bash
# Query delivery history (advanced)
sqlite3 datafold.db "SELECT * FROM delivery_log WHERE success = 0"
```

## Deduplication

Alerts are deduplicated to prevent spam:

1. **Status-based**: Same source + status + target = deduplicated
2. **Reason-based**: Same reasons hash = deduplicated
3. **Cooldown**: No repeat alerts within `cooldown_minutes`

### Cooldown Behavior

```yaml
alerting:
  cooldown_minutes: 60
```

After sending an alert:
- Same source + target won't alert again for 60 minutes
- Even if the specific reasons change
- Recovery alerts reset the cooldown

## Testing Webhooks

```bash
# Test all webhooks
datafold test-webhook

# Test specific webhook
datafold test-webhook --target slack
```

Test payloads use `event_type: info` and are always sent (ignore cooldown).

## Troubleshooting

### Webhook Not Receiving Alerts

1. Check events configuration:
   ```yaml
   events: [anomaly, recovery]  # Must include the event type
   ```

2. Check cooldown:
   ```bash
   datafold status  # See last alert times
   ```

3. Check delivery logs:
   ```bash
   sqlite3 datafold.db "SELECT * FROM delivery_log ORDER BY delivered_at DESC LIMIT 10"
   ```

### Signature Verification Failing

1. Use raw request body (not parsed JSON)
2. Ensure secret matches exactly (no extra whitespace)
3. Check for encoding issues (UTF-8)

### Timeouts

Increase timeout if your endpoint is slow:
```yaml
webhooks:
  - name: slow-endpoint
    timeout_seconds: 30  # Default is 10
```
