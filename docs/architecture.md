# Architecture

Internal design and component overview.

## High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         CLI Layer                                │
│  (init, validate, check, run, status, history, explain, ...)   │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      Core Components                             │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────┐ │
│  │  Connector  │  │  Detection  │  │    Alerting Pipeline    │ │
│  │   (SQL)     │──│   Engine    │──│  (Webhook + Dedup)      │ │
│  └─────────────┘  └─────────────┘  └─────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      Storage Layer                               │
│                     (SQLite Backend)                             │
│  ┌───────────┐  ┌─────────────┐  ┌───────────────────────────┐ │
│  │ Snapshots │  │ Alert State │  │     Delivery Log          │ │
│  └───────────┘  └─────────────┘  └───────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

## Component Diagram

```
                    ┌──────────────┐
                    │   Config     │
                    │  (YAML +     │
                    │   Pydantic)  │
                    └──────┬───────┘
                           │
              ┌────────────┴────────────┐
              │                         │
              ▼                         ▼
     ┌─────────────────┐      ┌─────────────────┐
     │   SQL Connector │      │  State Store    │
     │                 │      │   (SQLite)      │
     │ - postgres      │      │                 │
     │ - mysql         │      │ - snapshots     │
     │ - clickhouse    │      │ - alert_states  │
     │ - sqlite        │      │ - delivery_log  │
     └────────┬────────┘      └────────┬────────┘
              │                        │
              │   ┌────────────────────┘
              │   │
              ▼   ▼
     ┌─────────────────┐
     │ Detection Engine│
     │                 │
     │ - baseline calc │
     │ - freshness     │
     │ - volume        │
     └────────┬────────┘
              │
              ▼
     ┌─────────────────┐
     │ Alerting        │
     │ Pipeline        │
     │                 │
     │ - deduplication │
     │ - cooldown      │
     │ - webhook send  │
     └─────────────────┘
```

## Directory Structure

```
src/datafold/
├── __init__.py           # Package version
├── config.py             # Configuration models (Pydantic)
├── models.py             # Core data models
│
├── cli/
│   ├── __init__.py
│   ├── main.py           # Click CLI entry point
│   └── commands.py       # Command implementations
│
├── connectors/
│   ├── __init__.py
│   ├── base.py           # Connector interface
│   └── sql.py            # SQLAlchemy-based SQL connector
│
├── detection/
│   ├── __init__.py
│   └── engine.py         # Baseline calculation, anomaly detection
│
├── alerting/
│   ├── __init__.py
│   ├── webhook.py        # Webhook delivery, HMAC signing
│   └── pipeline.py       # Alert orchestration, deduplication
│
└── storage/
    ├── __init__.py
    ├── base.py           # Storage interface
    └── sqlite.py         # SQLite implementation
```

## Core Data Models

### DataSnapshot

Represents a single data collection:

```python
@dataclass
class DataSnapshot:
    source_name: str
    collected_at: datetime
    collect_status: CollectStatus  # SUCCESS, COLLECT_FAILED
    row_count: int | None
    latest_timestamp: datetime | None
    metrics: dict[str, Any]
    metadata: dict[str, Any]
```

### Decision

Result of detection analysis:

```python
@dataclass
class Decision:
    status: DecisionStatus  # OK, WARNING, ANOMALY
    reasons: list[Reason]
    metrics: dict[str, Any]
    baseline_summary: BaselineSummary | None
    confidence: float
```

### AlertState

Per-source, per-target alert tracking:

```python
@dataclass
class AlertState:
    source_name: str
    target_name: str
    notified_status: DecisionStatus
    notified_reason_hash: str
    last_change_at: datetime
    last_sent_at: datetime
    cooldown_until: datetime
```

## Data Flow

### Check Command

```
1. Load config (YAML → Pydantic models)
2. Initialize storage (SQLite)
3. For each enabled source:
   a. Check schedule (cron expression)
   b. Connect to data source
   c. Execute query
   d. Create DataSnapshot
   e. Save to storage
   f. Load historical snapshots
   g. Calculate baseline
   h. Run detection (freshness + volume)
   i. Create Decision
   j. Process alerts (dedup, cooldown, send)
4. Return exit code (0=OK, 2=anomaly)
```

### Detection Flow

```
                    ┌──────────────┐
                    │ DataSnapshot │
                    │  (current)   │
                    └──────┬───────┘
                           │
                           ▼
              ┌────────────────────────┐
              │  Load History          │
              │  (last N snapshots)    │
              └────────────┬───────────┘
                           │
                           ▼
              ┌────────────────────────┐
              │  Calculate Baseline    │
              │  - median, stddev      │
              │  - expected interval   │
              └────────────┬───────────┘
                           │
           ┌───────────────┴───────────────┐
           │                               │
           ▼                               ▼
┌────────────────────┐         ┌────────────────────┐
│  Freshness Check   │         │   Volume Check     │
│                    │         │                    │
│  - max_age_hours   │         │  - min_row_count   │
│  - baseline factor │         │  - deviation_factor│
└─────────┬──────────┘         └─────────┬──────────┘
          │                              │
          └──────────────┬───────────────┘
                         │
                         ▼
              ┌────────────────────────┐
              │   Determine Status     │
              │   (OK/WARNING/ANOMALY) │
              └────────────────────────┘
```

### Alert Flow

```
              ┌──────────────┐
              │   Decision   │
              └──────┬───────┘
                     │
                     ▼
         ┌───────────────────────┐
         │  For each webhook:    │
         │                       │
         │  1. Load AlertState   │
         │  2. Check cooldown    │
         │  3. Check dedup       │
         └───────────┬───────────┘
                     │
        ┌────────────┴────────────┐
        │ Should send?            │
        ├─────────┬───────────────┤
        │ Yes     │       No      │
        ▼         │               │
┌───────────────┐ │               │
│ Build payload │ │               │
│ Sign (HMAC)   │ │               │
│ Send HTTP     │ │               │
│ Retry on fail │ │               │
└───────┬───────┘ │               │
        │         │               │
        ▼         │               │
┌───────────────┐ │               │
│ Update state  │ │               │
│ Log delivery  │ │               │
└───────────────┘ │               │
        │         │               │
        └─────────┴───────────────┘
```

## SQLite Schema

```sql
-- Snapshots table
CREATE TABLE snapshots (
    id INTEGER PRIMARY KEY,
    source_name TEXT NOT NULL,
    collected_at TEXT NOT NULL,
    collect_status TEXT NOT NULL,
    row_count INTEGER,
    latest_timestamp TEXT,
    metrics_json TEXT,
    metadata_json TEXT,
    duration_ms INTEGER,
    error_code TEXT,
    error_message TEXT
);

-- Alert state (per source + target)
CREATE TABLE alert_states (
    id INTEGER PRIMARY KEY,
    source_name TEXT NOT NULL,
    target_name TEXT NOT NULL,
    notified_status TEXT,
    notified_reason_hash TEXT,
    last_change_at TEXT,
    last_sent_at TEXT,
    cooldown_until TEXT,
    UNIQUE(source_name, target_name)
);

-- Delivery log
CREATE TABLE delivery_log (
    id INTEGER PRIMARY KEY,
    source_name TEXT NOT NULL,
    target_name TEXT NOT NULL,
    event_type TEXT NOT NULL,
    payload_hash TEXT,
    delivered_at TEXT NOT NULL,
    success INTEGER NOT NULL,
    status_code INTEGER,
    latency_ms INTEGER,
    error_message TEXT
);

-- Schema metadata
CREATE TABLE schema_meta (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);
```

## Extension Points

### Custom Connectors

Implement the `Connector` interface:

```python
from datafold.connectors.base import Connector, DataSnapshot

class MyConnector(Connector):
    def collect(self, config: SourceConfig) -> DataSnapshot:
        # Your collection logic
        pass
```

### Custom Storage

Implement the `StateStore` interface:

```python
from datafold.storage.base import StateStore

class PostgresStateStore(StateStore):
    def append_snapshot(self, snapshot: DataSnapshot) -> int:
        # Store in Postgres
        pass
    
    # ... other methods
```

## Performance Considerations

- **SQLite**: Single-writer, use WAL mode (default)
- **Connections**: One per check, closed after
- **History queries**: Indexed by source_name + collected_at
- **Baseline**: Calculated on-demand, not cached
- **Memory**: Minimal footprint (~50MB typical)

## Security Model

- **Secrets**: Environment variables only
- **Validation**: Rejects hardcoded passwords
- **HMAC**: SHA-256 signatures for webhooks
- **Container**: Runs as non-root user
- **Network**: Outbound only (webhooks)
