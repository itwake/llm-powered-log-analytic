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

Uploads use `LOGAN_OBJECT_STORE_BACKEND=local` by default. The API returns an authenticated
`PUT /api/cases/{case_id}/uploads/{file_id}/content` URL, writes raw bytes to
`LOGAN_LOCAL_OBJECT_STORE_DIR` or `.logan/object-store`, records a `file://` object URI, and
passes completed upload paths to the worker pipeline through `input_file_ids`.

The default API path uses real GitHub Copilot auth and model calls:

- `POST /api/copilot/auth/start` starts GitHub device-code auth.
- `POST /api/copilot/auth/check` stores only an encrypted `github_source_oauth` credential when authorized.
- analysis runs use `CopilotModelGateway` and require a stored credential or one of `LOGAN_GITHUB_COPILOT_TOKEN` / `LOGAN_GITHUB_SOURCE_TOKEN`.

The test suite injects fake auth/model clients and does not require GitHub network access.

Run the web workspace against the local API:

```bash
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000 corepack pnpm --filter @logan/web dev
```

`NEXT_PUBLIC_API_BASE_URL` defaults to `http://localhost:8000`. The web client sends
browser requests with `credentials: "include"` for the `logan_session` cookie. The current
workbench creates cases, uploads selected log/archive files, starts analysis by
`input_file_ids`, preserves a sample/local fixture run action, lists real runs, loads report
views from API endpoints, submits feedback/exports, and drives Copilot device auth start/check
through the backend.

Run the full service skeleton:

```bash
docker compose up --build
```

## Remaining Staged Work

- Fan out serialized `AnalysisResult` artifacts into normalized PostgreSQL tables, ClickHouse, and OpenSearch.
- Persist enriched logs and window aggregates into ClickHouse.
- Index redacted/normalized logs into OpenSearch.
- Add an S3/MinIO presigned object-store adapter for production deployments.
- Add resumable/multipart uploads for large files and interrupted browser sessions.
- Cache Copilot plugin tokens until their `expires_at` instead of exchanging the source token per model call.
- Add credential revocation/disconnect endpoints and UI.
- Implement Copilot `/responses` streaming plus `/api/chat/stream` SSE.
- Back Temporal activities with durable idempotency records and retry state.
- Add PGEM and Granger methods behind the current causal method seams.
- Expand RBAC, collaborators, admin settings, audit log UI/API, retention jobs, and rate limits.
- Add Playwright e2e tests once the web app is connected to a running API.
- Consider ECharts/Cytoscape or similar libraries for richer temporal and graph visualization.
- Add Prometheus/OpenTelemetry instrumentation.

These gaps are explicitly deferred from this first foundation commit; they are not hidden behind static stubs in the tested local path.
