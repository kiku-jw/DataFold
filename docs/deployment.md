# Deployment

Production deployment guides for DataFold.

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
docker pull ghcr.io/datafold/agent:latest
```

### Run Check

```bash
docker run --rm \
  -v $(pwd)/datafold.yaml:/app/datafold.yaml:ro \
  -e DATABASE_URL="postgresql://..." \
  -e SLACK_WEBHOOK_URL="https://..." \
  ghcr.io/datafold/agent:latest \
  check --force
```

### Run Daemon

```bash
docker run -d \
  --name datafold \
  --restart unless-stopped \
  -v $(pwd)/datafold.yaml:/app/datafold.yaml:ro \
  -v datafold-data:/app/data \
  -e DATABASE_URL="postgresql://..." \
  -e SLACK_WEBHOOK_URL="https://..." \
  ghcr.io/datafold/agent:latest \
  run
```

### Build Custom Image

```dockerfile
FROM ghcr.io/datafold/agent:latest

# Add custom drivers
RUN pip install snowflake-connector-python

# Add your config
COPY datafold.yaml /app/datafold.yaml
```

## Docker Compose

### Development

```yaml
# docker-compose.yaml
version: "3.8"

services:
  datafold:
    image: ghcr.io/datafold/agent:latest
    command: run
    restart: unless-stopped
    environment:
      - DATABASE_URL=${DATABASE_URL}
      - SLACK_WEBHOOK_URL=${SLACK_WEBHOOK_URL}
    volumes:
      - ./datafold.yaml:/app/datafold.yaml:ro
      - datafold-data:/app/data
    healthcheck:
      test: ["CMD", "datafold", "status"]
      interval: 60s
      timeout: 10s
      retries: 3

volumes:
  datafold-data:
```

### With PostgreSQL (for testing)

```yaml
version: "3.8"

services:
  datafold:
    image: ghcr.io/datafold/agent:latest
    command: run
    depends_on:
      postgres:
        condition: service_healthy
    environment:
      - DATABASE_URL=postgresql://datafold:datafold@postgres:5432/testdb
    volumes:
      - ./datafold.yaml:/app/datafold.yaml:ro
      - datafold-data:/app/data

  postgres:
    image: postgres:15
    environment:
      POSTGRES_USER: datafold
      POSTGRES_PASSWORD: datafold
      POSTGRES_DB: testdb
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U datafold"]
      interval: 5s
      timeout: 5s
      retries: 5
    volumes:
      - postgres-data:/var/lib/postgresql/data

volumes:
  datafold-data:
  postgres-data:
```

## Kubernetes

### CronJob (Recommended)

Best for scheduled checks:

```yaml
# datafold-cronjob.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: datafold-config
data:
  datafold.yaml: |
    version: "1"
    agent:
      id: k8s-datafold
    storage:
      backend: sqlite
      path: /data/datafold.db
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
  name: datafold-secrets
type: Opaque
stringData:
  DATABASE_URL: "postgresql://user:pass@host:5432/db"
  SLACK_WEBHOOK_URL: "https://hooks.slack.com/services/..."
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: datafold-data
spec:
  accessModes: [ReadWriteOnce]
  resources:
    requests:
      storage: 1Gi
---
apiVersion: batch/v1
kind: CronJob
metadata:
  name: datafold
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
            - name: datafold
              image: ghcr.io/datafold/agent:latest
              command: ["datafold", "check", "--force"]
              envFrom:
                - secretRef:
                    name: datafold-secrets
              volumeMounts:
                - name: config
                  mountPath: /app/datafold.yaml
                  subPath: datafold.yaml
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
                name: datafold-config
            - name: data
              persistentVolumeClaim:
                claimName: datafold-data
```

Deploy:
```bash
kubectl apply -f datafold-cronjob.yaml
```

### Deployment (Daemon Mode)

For continuous monitoring:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: datafold
spec:
  replicas: 1
  selector:
    matchLabels:
      app: datafold
  template:
    metadata:
      labels:
        app: datafold
    spec:
      containers:
        - name: datafold
          image: ghcr.io/datafold/agent:latest
          command: ["datafold", "run"]
          envFrom:
            - secretRef:
                name: datafold-secrets
          volumeMounts:
            - name: config
              mountPath: /app/datafold.yaml
              subPath: datafold.yaml
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
              command: ["datafold", "status"]
            initialDelaySeconds: 30
            periodSeconds: 60
      volumes:
        - name: config
          configMap:
            name: datafold-config
        - name: data
          persistentVolumeClaim:
            claimName: datafold-data
```

## Systemd (Linux)

### Install

```bash
pip install datafold-agent
```

### Create Service

```ini
# /etc/systemd/system/datafold.service
[Unit]
Description=DataFold Agent
After=network.target

[Service]
Type=simple
User=datafold
Group=datafold
WorkingDirectory=/opt/datafold
ExecStart=/usr/local/bin/datafold run
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
sudo systemctl enable datafold
sudo systemctl start datafold
sudo systemctl status datafold
```

### View Logs

```bash
sudo journalctl -u datafold -f
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
- [ ] Regular `datafold purge` scheduled
- [ ] Backup strategy for state database

## Scaling

DataFold is designed for single-instance operation. For multi-region:

1. Deploy one agent per region
2. Use unique `agent.id` for each
3. Configure region-specific webhooks
4. (Future) Use shared Postgres backend

## Monitoring DataFold Itself

Monitor the DataFold agent:

```yaml
# External healthcheck
sources:
  - name: datafold_self
    type: sql
    dialect: sqlite
    connection: /data/datafold.db
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
datafold status && echo "healthy" || echo "unhealthy"
```
