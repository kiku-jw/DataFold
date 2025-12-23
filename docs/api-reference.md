# API Reference

Python API for extending DriftGuard.

## Installation

```bash
pip install driftguard-agent
```

## Quick Example

```python
from pathlib import Path
from driftguard.config import load_config
from driftguard.storage.sqlite import SQLiteStateStore
from driftguard.connectors.sql import SQLConnector
from driftguard.detection.engine import DetectionEngine

# Load config
config = load_config(Path("driftguard.yaml"))

# Initialize storage
store = SQLiteStateStore(config.storage.path)
store.init()

# Create connector and engine
connector = SQLConnector()
engine = DetectionEngine(config.baseline)

# Check a source
source = config.sources[0]
snapshot = connector.collect(source)
store.append_snapshot(snapshot)

history = store.list_snapshots(source.name, limit=20)
decision = engine.analyze(snapshot, history, source)

print(f"Status: {decision.status.value}")
for reason in decision.reasons:
    print(f"  - {reason.message}")

store.close()
```

## Configuration

### load_config

```python
from driftguard.config import load_config, DriftGuardConfig

def load_config(path: Path) -> DriftGuardConfig:
    """Load and validate configuration from YAML file."""
```

**Parameters:**
- `path`: Path to YAML config file

**Returns:** `DriftGuardConfig` object

**Raises:** `ConfigError` if invalid

### DriftGuardConfig

```python
@dataclass
class DriftGuardConfig:
    version: str
    agent: AgentConfig
    storage: StorageConfig
    sources: list[SourceConfig]
    alerting: AlertingConfig
    retention: RetentionConfig
    baseline: BaselineConfig
```

### SourceConfig

```python
@dataclass
class SourceConfig:
    name: str
    type: str
    dialect: str
    connection: str
    query: str
    schedule: str
    enabled: bool = True
    freshness: FreshnessConfig
    volume: VolumeConfig
    timeout_seconds: int = 30
```

### Environment Variable Resolution

```python
from driftguard.config import resolve_env_vars

# Resolves ${VAR} patterns
url = resolve_env_vars("postgresql://${DB_USER}:${DB_PASS}@host/db")
```

## Models

### DataSnapshot

```python
from driftguard.models import DataSnapshot, CollectStatus

snapshot = DataSnapshot(
    source_name="orders",
    collected_at=datetime.now(timezone.utc),
    collect_status=CollectStatus.SUCCESS,
    row_count=1000,
    latest_timestamp=datetime.now(timezone.utc),
    metrics={"row_count": 1000},
    metadata={"duration_ms": 45}
)
```

### Decision

```python
from driftguard.models import Decision, DecisionStatus, Reason

decision = Decision(
    status=DecisionStatus.OK,
    reasons=[],
    metrics={"row_count": 1000},
    baseline_summary=baseline,
    confidence=0.95
)

# Check status
if decision.status == DecisionStatus.ANOMALY:
    for reason in decision.reasons:
        print(f"{reason.code}: {reason.message}")
```

### DecisionStatus

```python
from driftguard.models import DecisionStatus

DecisionStatus.OK       # All checks passed
DecisionStatus.WARNING  # Deviation detected
DecisionStatus.ANOMALY  # Critical issue
DecisionStatus.UNKNOWN  # Not yet determined
```

### Reason

```python
from driftguard.models import Reason

reason = Reason(
    code="VOLUME_BELOW_MINIMUM",
    message="Row count 50 is below minimum threshold of 100",
    severity="critical",
    details={"actual": 50, "threshold": 100}
)
```

### AlertState

```python
from driftguard.models import AlertState

state = AlertState(
    source_name="orders",
    target_name="slack",
    notified_status=DecisionStatus.ANOMALY,
    notified_reason_hash="abc123",
    last_change_at=datetime.now(timezone.utc),
    last_sent_at=datetime.now(timezone.utc),
    cooldown_until=datetime.now(timezone.utc) + timedelta(hours=1)
)

# Check if should alert
if state.should_alert(new_decision, cooldown_minutes=60):
    send_alert()
```

### WebhookPayload

```python
from driftguard.models import WebhookPayload, EventType

payload = WebhookPayload(
    event_type=EventType.ANOMALY,
    source_name="orders",
    source_type="sql",
    decision=decision.to_dict(),
    metrics=snapshot.metrics,
    baseline_summary=baseline.to_dict(),
    agent_id="my-agent"
)

# Get canonical JSON (for signing)
json_str = payload.to_canonical_json()

# Get as dict
data = payload.to_dict()
```

## Connectors

### SQLConnector

```python
from driftguard.connectors.sql import SQLConnector
from driftguard.config import SourceConfig

connector = SQLConnector(timeout_seconds=30)

# Collect with error handling
snapshot = connector.collect_with_error_handling(source_config)

# Or collect directly (raises on error)
try:
    snapshot = connector.collect(source_config)
except ConnectionError as e:
    print(f"Connection failed: {e}")
except QueryError as e:
    print(f"Query failed: {e}")
```

### Custom Connector

```python
from driftguard.connectors.base import Connector
from driftguard.models import DataSnapshot

class MyConnector(Connector):
    """Custom connector implementation."""
    
    def collect(self, config: SourceConfig) -> DataSnapshot:
        # Your collection logic
        data = fetch_from_api(config.connection)
        
        return DataSnapshot(
            source_name=config.name,
            collected_at=datetime.now(timezone.utc),
            collect_status=CollectStatus.SUCCESS,
            row_count=len(data),
            latest_timestamp=max(d['timestamp'] for d in data),
            metrics={"row_count": len(data)},
            metadata={}
        )
    
    def collect_with_error_handling(self, config: SourceConfig) -> DataSnapshot:
        try:
            return self.collect(config)
        except Exception as e:
            return DataSnapshot(
                source_name=config.name,
                collected_at=datetime.now(timezone.utc),
                collect_status=CollectStatus.COLLECT_FAILED,
                row_count=None,
                latest_timestamp=None,
                metrics={},
                metadata={"error_message": str(e)}
            )
```

## Detection Engine

### DetectionEngine

```python
from driftguard.detection.engine import DetectionEngine
from driftguard.config import BaselineConfig

engine = DetectionEngine(BaselineConfig(
    window_size=20,
    max_age_days=30
))

# Analyze a snapshot
decision = engine.analyze(
    current=snapshot,
    history=previous_snapshots,
    source_config=source
)

print(f"Status: {decision.status}")
print(f"Confidence: {decision.confidence}")
print(f"Baseline: {decision.baseline_summary}")
```

### BaselineSummary

```python
from driftguard.models import BaselineSummary

baseline = BaselineSummary(
    snapshot_count=20,
    row_count_median=1000.0,
    row_count_min=900.0,
    row_count_max=1100.0,
    row_count_stddev=50.0,
    expected_interval_seconds=3600.0,
    oldest_snapshot_at=datetime(...),
    newest_snapshot_at=datetime(...)
)

# Convert to dict
data = baseline.to_dict()
```

## Storage

### SQLiteStateStore

```python
from driftguard.storage.sqlite import SQLiteStateStore

store = SQLiteStateStore("/path/to/driftguard.db")
store.init()  # Creates tables if needed
store.migrate()  # Apply migrations

# Snapshots
snapshot_id = store.append_snapshot(snapshot)
last = store.get_last_snapshot("orders")
history = store.list_snapshots(
    source_name="orders",
    limit=20,
    max_age_days=30,
    success_only=True
)

# Alert state
state = store.get_alert_state("orders", "slack")
store.set_alert_state(new_state)

# Delivery log
store.log_delivery(
    source_name="orders",
    target_name="slack",
    event_type="anomaly",
    payload_hash="abc123",
    result=delivery_result
)

# Maintenance
deleted = store.purge_old_snapshots(
    max_age_days=30,
    min_per_source=10
)

store.close()
```

### StateStore Interface

```python
from driftguard.storage.base import StateStore

class MyStore(StateStore):
    """Custom storage backend."""
    
    def init(self) -> None: ...
    def close(self) -> None: ...
    def migrate(self) -> None: ...
    def append_snapshot(self, snapshot: DataSnapshot) -> int: ...
    def get_last_snapshot(self, source_name: str) -> DataSnapshot | None: ...
    def list_snapshots(self, source_name: str, ...) -> list[DataSnapshot]: ...
    def get_alert_state(self, source_name: str, target_name: str) -> AlertState | None: ...
    def set_alert_state(self, state: AlertState) -> None: ...
    def log_delivery(self, ...) -> None: ...
    def purge_old_snapshots(self, ...) -> int: ...
```

## Alerting

### WebhookDelivery

```python
from driftguard.alerting.webhook import WebhookDelivery
from driftguard.config import WebhookConfig

delivery = WebhookDelivery(max_retries=3)

# Build payload
payload = delivery.build_payload(
    source_name="orders",
    source_type="sql",
    event_type=EventType.ANOMALY,
    decision_dict=decision.to_dict(),
    metrics=snapshot.metrics,
    baseline_dict=baseline.to_dict(),
    agent_id="my-agent"
)

# Send
webhook_config = WebhookConfig(
    name="slack",
    url="https://hooks.slack.com/...",
    secret="my-secret"
)

result = delivery.deliver(payload, webhook_config)

if result.success:
    print(f"Delivered in {result.latency_ms}ms")
else:
    print(f"Failed: {result.error_message}")
```

### AlertingPipeline

```python
from driftguard.alerting.pipeline import AlertingPipeline

pipeline = AlertingPipeline(
    config=alerting_config,
    store=store,
    agent_id="my-agent",
    dry_run=False
)

# Process decision and send alerts
results = pipeline.process(source_config, decision)
# Returns: {"slack": True, "pagerduty": False}
```

## CLI Integration

### Programmatic CLI

```python
from click.testing import CliRunner
from driftguard.cli.main import cli

runner = CliRunner()

# Run check
result = runner.invoke(cli, ['check', '--force'])
print(result.output)
print(f"Exit code: {result.exit_code}")

# Get status as JSON
result = runner.invoke(cli, ['status', '--json'])
import json
status = json.loads(result.output)
```

## Type Hints

All public APIs are fully typed:

```python
from driftguard.models import DataSnapshot, Decision
from driftguard.config import SourceConfig
from driftguard.storage.base import StateStore

def my_function(
    snapshot: DataSnapshot,
    config: SourceConfig,
    store: StateStore
) -> Decision:
    ...
```
