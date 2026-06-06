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

By default the API uses the lightweight in-memory store unless a database URL is configured.
Set `LOGAN_DATABASE_URL=sqlite:////tmp/logan.db` for local durable metadata, or use a
PostgreSQL URL such as `postgresql+psycopg://logan:logan@postgres:5432/logan`.
`LOGAN_STORE_BACKEND=auto` selects SQLAlchemy when `LOGAN_DATABASE_URL` is set; `memory`
and `sqlalchemy` force a backend explicitly.

Run the full service skeleton:

```bash
docker compose up --build
```

## Remaining Staged Work

- Fan out serialized `AnalysisResult` artifacts into normalized PostgreSQL tables, ClickHouse, and OpenSearch.
- Persist enriched logs and window aggregates into ClickHouse.
- Index redacted/normalized logs into OpenSearch.
- Implement real S3/MinIO object bytes and presigned uploads instead of durable metadata placeholders.
- Implement real GitHub source OAuth polling and Copilot plugin token exchange.
- Implement real `CopilotModelGateway.responses` network calls to the Copilot plugin `/responses` runtime.
- Back Temporal activities with durable idempotency records and retry state.
- Add PGEM and Granger methods behind the current causal method seams.
- Expand RBAC, collaborators, admin settings, audit log UI/API, retention jobs, and rate limits.
- Add Playwright e2e tests once the web app is connected to a running API.
- Add Prometheus/OpenTelemetry instrumentation.

These gaps are explicitly deferred from this first foundation commit; they are not hidden behind static stubs in the tested local path.
