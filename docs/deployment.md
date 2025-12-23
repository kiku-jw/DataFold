# Deployment

Production deployment guides for DriftGuard.

## Deployment Options

| Method | Best For |
|--------|----------|
| **pip + systemd** | Single server, simple setup |
| **Docker** | Containerized environments |
| **Docker Compose** | Local development, small deployments |
| **Kubernetes CronJob** | Cloud-native, scalable |
| **Kubernetes Deployment** | Continuous daemon mode |

## Docker

### Pull Image

```bash
docker pull ghcr.io/driftguard/agent:latest
```

### Run Check

```bash
docker run --rm \
  -v $(pwd)/driftguard.yaml:/app/driftguard.yaml:ro \
  -e DATABASE_URL="postgresql://..." \
  -e SLACK_WEBHOOK_URL="https://..." \
  ghcr.io/driftguard/agent:latest \
  check --force
```

### Run Daemon

```bash
docker run -d \
  --name driftguard \
  --restart unless-stopped \
  -v $(pwd)/driftguard.yaml:/app/driftguard.yaml:ro \
  -v driftguard-data:/app/data \
  -e DATABASE_URL="postgresql://..." \
  -e SLACK_WEBHOOK_URL="https://..." \
  ghcr.io/driftguard/agent:latest \
  run
```

### Build Custom Image

```dockerfile
FROM ghcr.io/driftguard/agent:latest

# Add custom drivers
RUN pip install snowflake-connector-python

# Add your config
COPY driftguard.yaml /app/driftguard.yaml
```

## Docker Compose

### Development

```yaml
# docker-compose.yaml
version: "3.8"

services:
  driftguard:
    image: ghcr.io/driftguard/agent:latest
    command: run
    restart: unless-stopped
    environment:
      - DATABASE_URL=${DATABASE_URL}
      - SLACK_WEBHOOK_URL=${SLACK_WEBHOOK_URL}
    volumes:
      - ./driftguard.yaml:/app/driftguard.yaml:ro
      - driftguard-data:/app/data
    healthcheck:
      test: ["CMD", "driftguard", "status"]
      interval: 60s
      timeout: 10s
      retries: 3

volumes:
  driftguard-data:
```

### With PostgreSQL (for testing)

```yaml
version: "3.8"

services:
  driftguard:
    image: ghcr.io/driftguard/agent:latest
    command: run
    depends_on:
      postgres:
        condition: service_healthy
    environment:
      - DATABASE_URL=postgresql://driftguard:driftguard@postgres:5432/testdb
    volumes:
      - ./driftguard.yaml:/app/driftguard.yaml:ro
      - driftguard-data:/app/data

  postgres:
    image: postgres:15
    environment:
      POSTGRES_USER: driftguard
      POSTGRES_PASSWORD: driftguard
      POSTGRES_DB: testdb
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U driftguard"]
      interval: 5s
      timeout: 5s
      retries: 5
    volumes:
      - postgres-data:/var/lib/postgresql/data

volumes:
  driftguard-data:
  postgres-data:
```

## Kubernetes

### CronJob (Recommended)

Best for scheduled checks:

```yaml
# driftguard-cronjob.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: driftguard-config
data:
  driftguard.yaml: |
    version: "1"
    agent:
      id: k8s-driftguard
    storage:
      backend: sqlite
      path: /data/driftguard.db
    sources:
      - name: orders
        type: sql
        dialect: postgres
        connection: ${DATABASE_URL}
        query: |
          SELECT COUNT(*) as row_count,
                 MAX(created_at) as latest_timestamp
          FROM orders
        schedule: "*/15 * * * *"
    alerting:
      webhooks:
        - name: slack
          url: ${SLACK_WEBHOOK_URL}
          events: [anomaly, recovery]
---
apiVersion: v1
kind: Secret
metadata:
  name: driftguard-secrets
type: Opaque
stringData:
  DATABASE_URL: "postgresql://user:pass@host:5432/db"
  SLACK_WEBHOOK_URL: "https://hooks.slack.com/services/..."
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: driftguard-data
spec:
  accessModes: [ReadWriteOnce]
  resources:
    requests:
      storage: 1Gi
---
apiVersion: batch/v1
kind: CronJob
metadata:
  name: driftguard
spec:
  schedule: "*/15 * * * *"
  concurrencyPolicy: Forbid
  successfulJobsHistoryLimit: 3
  failedJobsHistoryLimit: 3
  jobTemplate:
    spec:
      backoffLimit: 2
      template:
        spec:
          restartPolicy: OnFailure
          containers:
            - name: driftguard
              image: ghcr.io/driftguard/agent:latest
              command: ["driftguard", "check", "--force"]
              envFrom:
                - secretRef:
                    name: driftguard-secrets
              volumeMounts:
                - name: config
                  mountPath: /app/driftguard.yaml
                  subPath: driftguard.yaml
                - name: data
                  mountPath: /data
              resources:
                requests:
                  memory: "64Mi"
                  cpu: "100m"
                limits:
                  memory: "256Mi"
                  cpu: "500m"
          volumes:
            - name: config
              configMap:
                name: driftguard-config
            - name: data
              persistentVolumeClaim:
                claimName: driftguard-data
```

Deploy:
```bash
kubectl apply -f driftguard-cronjob.yaml
```

### Deployment (Daemon Mode)

For continuous monitoring:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: driftguard
spec:
  replicas: 1
  selector:
    matchLabels:
      app: driftguard
  template:
    metadata:
      labels:
        app: driftguard
    spec:
      containers:
        - name: driftguard
          image: ghcr.io/driftguard/agent:latest
          command: ["driftguard", "run"]
          envFrom:
            - secretRef:
                name: driftguard-secrets
          volumeMounts:
            - name: config
              mountPath: /app/driftguard.yaml
              subPath: driftguard.yaml
            - name: data
              mountPath: /data
          resources:
            requests:
              memory: "64Mi"
              cpu: "100m"
            limits:
              memory: "256Mi"
              cpu: "500m"
          livenessProbe:
            exec:
              command: ["driftguard", "status"]
            initialDelaySeconds: 30
            periodSeconds: 60
      volumes:
        - name: config
          configMap:
            name: driftguard-config
        - name: data
          persistentVolumeClaim:
            claimName: driftguard-data
```

## Systemd (Linux)

### Install

```bash
pip install driftguard-agent
```

### Create Service

```ini
# /etc/systemd/system/driftguard.service
[Unit]
Description=DriftGuard Agent
After=network.target

[Service]
Type=simple
User=driftguard
Group=driftguard
WorkingDirectory=/opt/driftguard
ExecStart=/usr/local/bin/driftguard run
Restart=always
RestartSec=10
Environment=DATABASE_URL=postgresql://...
Environment=SLACK_WEBHOOK_URL=https://...

[Install]
WantedBy=multi-user.target
```

### Enable and Start

```bash
sudo systemctl daemon-reload
sudo systemctl enable driftguard
sudo systemctl start driftguard
sudo systemctl status driftguard
```

### View Logs

```bash
sudo journalctl -u driftguard -f
```

## Production Checklist

### Security

- [ ] Secrets in environment variables, not config file
- [ ] HMAC signatures enabled for webhooks
- [ ] Database credentials use least privilege
- [ ] Container runs as non-root user

### Reliability

- [ ] Persistent volume for SQLite state
- [ ] Health checks configured
- [ ] Restart policy set
- [ ] Resource limits defined

### Observability

- [ ] Logs accessible (stdout/stderr)
- [ ] Alert cooldown configured appropriately
- [ ] Test webhooks verified working

### Maintenance

- [ ] Retention policy configured
- [ ] Regular `driftguard purge` scheduled
- [ ] Backup strategy for state database

## Scaling

DriftGuard is designed for single-instance operation. For multi-region:

1. Deploy one agent per region
2. Use unique `agent.id` for each
3. Configure region-specific webhooks
4. (Future) Use shared Postgres backend

## Monitoring DriftGuard Itself

Monitor the DriftGuard agent:

```yaml
# External healthcheck
sources:
  - name: driftguard_self
    type: sql
    dialect: sqlite
    connection: /data/driftguard.db
    query: |
      SELECT COUNT(*) as row_count,
             MAX(collected_at) as latest_timestamp
      FROM snapshots
      WHERE collected_at >= datetime('now', '-1 hour')
    schedule: "*/30 * * * *"
    freshness:
      max_age_hours: 1
```

Or use external monitoring:
```bash
# Healthcheck endpoint (returns exit code)
driftguard status && echo "healthy" || echo "unhealthy"
```
