FROM python:3.11-slim AS builder

WORKDIR /app

RUN pip install --no-cache-dir build

COPY pyproject.toml README.md ./
COPY src/ src/

RUN python -m build --wheel


FROM python:3.11-slim

WORKDIR /app

RUN groupadd -r driftguard && useradd -r -g driftguard driftguard

COPY --from=builder /app/dist/*.whl /tmp/

RUN pip install --no-cache-dir /tmp/*.whl && rm /tmp/*.whl

RUN pip install --no-cache-dir psycopg2-binary pymysql

RUN mkdir -p /app/data && chown -R driftguard:driftguard /app

USER driftguard

VOLUME ["/app/data"]

ENV DRIFTGUARD_STORAGE_PATH=/app/data/driftguard.db

ENTRYPOINT ["driftguard"]
CMD ["run"]

