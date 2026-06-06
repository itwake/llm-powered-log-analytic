# Operations

## Local

Run Python tests without external services:

```bash
python3 -m pytest tests
```

Run the API locally:

```bash
uvicorn app.main:app --reload --app-dir apps/api
```

Run the full service skeleton:

```bash
docker compose up --build
```

## Remaining Staged Work

- Replace in-memory API store with PostgreSQL repositories and Alembic migrations.
- Persist enriched logs and window aggregates into ClickHouse.
- Index redacted/normalized logs into OpenSearch.
- Implement real S3/MinIO presigned uploads instead of local object placeholders.
- Implement real GitHub source OAuth polling and Copilot plugin token exchange.
- Implement real `CopilotModelGateway.responses` network calls to the Copilot plugin `/responses` runtime.
- Back Temporal activities with durable idempotency records and retry state.
- Add PGEM and Granger methods behind the current causal method seams.
- Expand RBAC, collaborators, admin settings, audit logs, retention jobs, and rate limits.
- Add Playwright e2e tests once the web app is connected to a running API.
- Add Prometheus/OpenTelemetry instrumentation.

These gaps are explicitly deferred from this first foundation commit; they are not hidden behind static stubs in the tested local path.
