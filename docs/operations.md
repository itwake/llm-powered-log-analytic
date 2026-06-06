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

Set `LOGAN_OBJECT_STORE_BACKEND=s3` or `minio` to use presigned object-store uploads for raw
files. Required settings are `LOGAN_S3_BUCKET`, `LOGAN_S3_ACCESS_KEY`, and
`LOGAN_S3_SECRET_KEY`; `LOGAN_S3_ENDPOINT` is also required for `minio` and optional for AWS S3.
The defaults are `LOGAN_S3_REGION=us-east-1`, `LOGAN_S3_PRESIGN_EXPIRES_SECONDS=900`, and
`LOGAN_S3_FORCE_PATH_STYLE=true`. The API records `s3://` object URIs and returns presigned
`PUT` URLs with upload headers, then verifies completion with S3 `head_object` for existence and
size. S3-backed `input_file_ids` are intentionally rejected by the current local analysis path
until the worker supports streaming or downloading S3 inputs.

The default API path uses real GitHub Copilot auth and model calls:

- `POST /api/copilot/auth/start` starts GitHub device-code auth.
- `POST /api/copilot/auth/check` stores only an encrypted `github_source_oauth` credential when authorized.
- `DELETE /api/copilot/auth/credential` disconnects the current user by revoking stored source and plugin credentials.
- analysis runs use `CopilotModelGateway` and require a stored credential or one of `LOGAN_GITHUB_COPILOT_TOKEN` / `LOGAN_GITHUB_SOURCE_TOKEN`.

When stored source credentials are used, the gateway exchanges them for Copilot plugin tokens,
persists the plugin token with its `expires_at`, and reuses it until expiration. Set
`LOGAN_COPILOT_TOKEN_CACHE_SKEW_SECONDS=60` to control the pre-expiration refresh window.
`LOGAN_GITHUB_SOURCE_TOKEN` remains an environment fallback and is exchanged per call without
being written to the user credential store.

The test suite injects fake auth/model clients and does not require GitHub network access.
Analysis completion in the SQLAlchemy backend now writes normalized analytics rows into
PostgreSQL/SQLite tables in the same local path. ClickHouse/OpenSearch payload builders and
optional HTTP publishers are implemented, but external sinks are disabled by default and Docker
is not required for deterministic tests.
SQLAlchemy-backed report endpoints read summary, temporal, log table, causal graph, and causal
summary views from the normalized fan-out tables, with the in-memory backend and missing fan-out
rows still falling back to the legacy `analysis_runs.result_json` path.

Analysis orchestration defaults to the current synchronous local path:

- `LOGAN_ANALYSIS_ORCHESTRATOR=local` runs `AnalyzeCasePipeline` in the API process and keeps tests deterministic.
- `LOGAN_ANALYSIS_ORCHESTRATOR=temporal` uses the lazy Temporal client facade to start `AnalyzeCaseWorkflow`.
- `LOGAN_TEMPORAL_ADDRESS=temporal:7233`
- `LOGAN_TEMPORAL_NAMESPACE=default`
- `LOGAN_TEMPORAL_TASK_QUEUE=logan-analysis`

The Temporal facade imports the SDK only when temporal orchestration is selected and raises a
typed configuration/connectivity error if the SDK or server is unavailable. The real durable
worker/activity implementation is still staged work; the tested local path remains the source
of completed analysis results.

External analytics sinks can be enabled for SQLAlchemy-backed runs with:

- `LOGAN_ANALYTICS_SINKS_ENABLED=true`
- `LOGAN_CLICKHOUSE_URL=http://clickhouse:8123` for ClickHouse JSONEachRow inserts.
- `LOGAN_OPENSEARCH_URL=http://opensearch:9200` for OpenSearch `_bulk` indexing.
- `LOGAN_ANALYTICS_SINK_FAILURE_MODE=warn` to audit and continue on sink errors, or `fail`
  to fail the analysis run.

The adapters publish only redacted/normalized log content and derived metadata. They do not
publish raw log text, model prompts, model inputs, source tokens, or credential material.
ClickHouse/OpenSearch table/index creation, schema migrations, retries, idempotency records,
and service-backed external analytics queries remain production work.

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

- Add managed ClickHouse table lifecycle for `enriched_log_lines` and `window_aggregates`.
- Add managed OpenSearch index lifecycle for `logan-logs-{case_id}-{analysis_run_id}`.
- Add external sink retry/idempotency records for ClickHouse/OpenSearch writes.
- Add report/query reads over external analytics stores.
- Add resumable/multipart uploads for large files and interrupted browser sessions.
- Implement Copilot `/responses` streaming plus `/api/chat/stream` SSE.
- Replace the Temporal placeholder with real activities backed by durable retries and replay-safe
  idempotency; job event rows already provide the run-scoped progress/event stream.
- Add PGEM and Granger methods behind the current causal method seams.
- Expand RBAC, collaborators, admin settings, audit log UI/API, retention jobs, and rate limits.
- Add Playwright e2e tests once the web app is connected to a running API.
- Consider ECharts/Cytoscape or similar libraries for richer temporal and graph visualization.
- Add Prometheus/OpenTelemetry instrumentation.

These gaps are explicitly deferred from this first foundation commit; they are not hidden behind static stubs in the tested local path.
