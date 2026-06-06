# Operations

## Local

Run Python tests without external services:

```bash
python3 -m pytest tests
```

Run Playwright browser E2E after installing browser dependencies:

```bash
corepack pnpm exec playwright install --with-deps chromium
corepack pnpm e2e
```

The E2E config starts the API with:

- `python -m uvicorn app.main:app --app-dir apps/api --host 127.0.0.1 --port 8000`
- `LOGAN_STORE_BACKEND=memory`
- `LOGAN_OBJECT_STORE_BACKEND=local`
- `LOGAN_LOCAL_OBJECT_STORE_DIR=.logan/e2e-object-store`
- `LOGAN_RATE_LIMIT_ENABLED=false`
- `LOGAN_METRICS_ENABLED=true`
- `LOGAN_LLM_PROVIDER=mock`

It starts the web app with:

- `corepack pnpm --filter @logan/web dev --hostname 127.0.0.1 --port 3000`
- `NEXT_PUBLIC_API_BASE_URL=http://localhost:8000`

Tests navigate with `http://localhost:3000`, matching the API CORS allow-list. Existing local
servers are reused outside CI for debugging convenience; make sure they use the same local/mock
settings when relying on reuse. The suite registers unique users, creates a case, starts the
deterministic sample/local analysis fixture, and exercises Data Summary, Temporal View, Tabular
Logs, Causal Graph, and Causal Summary without external databases, MinIO, ClickHouse,
OpenSearch, Temporal, or real Copilot credentials. The memory store is process-local and clears
when the API server exits.

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

Large S3/MinIO raw uploads use multipart/resumable sessions when the client asks with
`multipart=true` or when the declared size reaches `LOGAN_S3_MULTIPART_THRESHOLD_BYTES`
(default `104857600`, 100 MiB). `LOGAN_S3_MULTIPART_PART_SIZE_BYTES` defaults to `67108864`
(64 MiB), and `LOGAN_S3_MULTIPART_MAX_PARTS` defaults to `10000`. Multipart session metadata is
stored on the upload record with safe fields such as upload mode, S3 upload id, part size, part
count, and abort timestamp; raw bytes, log content, credentials, and source tokens are never stored
there. Clients can resume with `GET /api/cases/{case_id}/uploads/{file_id}/multipart`, which
returns fresh part URLs and S3 `list_parts` data, or abort with `DELETE` on the same route. The
local backend intentionally remains a direct authenticated API `PUT`.

The default API path uses real GitHub Copilot auth and model calls:

- `POST /api/copilot/auth/start` starts GitHub device-code auth.
- `POST /api/copilot/auth/check` stores only an encrypted `github_source_oauth` credential when authorized.
- `DELETE /api/copilot/auth/credential` disconnects the current user by revoking stored source and plugin credentials.
- analysis runs use `CopilotModelGateway` and require a stored credential or one of `LOGAN_GITHUB_COPILOT_TOKEN` / `LOGAN_GITHUB_SOURCE_TOKEN`.
- case workspace chat uses `POST /api/chat/stream` to stream Copilot answers over SSE when a completed analysis result is available.

When stored source credentials are used, the gateway exchanges them for Copilot plugin tokens,
persists the plugin token with its `expires_at`, and reuses it until expiration. Set
`LOGAN_COPILOT_TOKEN_CACHE_SKEW_SECONDS=60` to control the pre-expiration refresh window.
`LOGAN_GITHUB_SOURCE_TOKEN` remains an environment fallback and is exchanged per call without
being written to the user credential store.

The chat stream route is authenticated by the same `logan_session` cookie as the rest of the API.
It sends only compact, redacted analysis context to Copilot: user question, case/run ids, causal
summary text, up to five evidence refs, and up to five template-level summary rows. If no context
exists, it streams a short fallback response without calling Copilot. Credential and gateway
failures are serialized as sanitized `event: error` SSE frames.

Access control is enforced in the API. Global `admin` users can access every case and the admin
routes. Global `engineer` users can create cases and access only cases they created or cases where
they are collaborators. New case creators are stored as `owner` collaborators. Case `owner`
collaborators can manage collaborators and perform edit actions; `editor` collaborators can upload
files, start analysis, submit feedback, and create exports; `viewer` collaborators can read case,
run, event, report, log, and chat context views but cannot mutate analysis/upload state. Read
routes hide inaccessible cases with `404`; mutating routes return `403` when the case exists but
the caller lacks the required role.

Admin-only routes live under `/api/admin`:

- `GET /api/admin/users`
- `PATCH /api/admin/users/{user_id}` for role and active-state changes
- `GET /api/admin/audit-logs`
- `GET /api/admin/settings`
- `POST /api/admin/retention/run`

Admin settings intentionally return only safe runtime shape: environment, selected store/object
backends, orchestrator, retention days, rate-limit settings, and analytics toggles. They do not
return database URLs, access keys, tokens, passwords, credential hints, or raw log text. The web app
adds an `Admin` nav item only for `user.role === "admin"` and exposes a minimal operational page
for these controls.

The test suite injects fake auth/model clients and does not require GitHub network access.
Analysis completion in the SQLAlchemy backend now writes normalized analytics rows into
PostgreSQL/SQLite tables in the same local path. ClickHouse/OpenSearch payload builders and
optional HTTP publishers are implemented with managed database/table/index lifecycle, but
external sinks are disabled by default and Docker is not required for deterministic tests.
SQLAlchemy-backed report endpoints read summary, temporal, log table, causal graph, and causal
summary views from the normalized fan-out tables, with the in-memory backend and missing fan-out
rows still falling back to the legacy `analysis_runs.result_json` path. Temporal and log table
reports can optionally try service-backed external analytics queries first when explicitly
enabled and backed by succeeded sink write records.

The worker causal graph emits candidate edges only. Each edge keeps `edge_type=candidate_cause`
and `needs_validation=true`, and evidence is intended to guide validation with metrics, traces,
deployments, and operator context rather than prove a definitive root cause. The default causal
methods are `temporal_precedence`, `lagged_correlation`, `lift`, `pgem`, and `granger_linear`.
`pgem` scores directed event transitions by source support, target coverage, baseline target-rate
lift, and median lag. `granger_linear` builds per-template count series and uses a deterministic
pure-Python lagged OLS fallback to estimate whether source-history counts improve target-count
prediction over target history alone; p-values are approximate and adjusted with
Benjamini-Hochberg FDR across tested directions.

Optional analysis config can tune these seams without changing API shape:

```json
{
  "causal": {
    "max_lag_seconds": 600,
    "time_bin_seconds": 60,
    "methods": ["temporal_precedence", "lagged_correlation", "lift", "pgem", "granger_linear"],
    "granger_max_lag_bins": 10
  }
}
```

If `causal.granger_max_lag_bins` is omitted, the worker derives it from
`max_lag_seconds / time_bin_seconds` with a bounded cap. Sparse or constant series return
unsupported method evidence with a reason, while temporal precedence and lift can still produce
candidate edges for small incidents.

Analysis orchestration defaults to the current synchronous local path:

- `LOGAN_ANALYSIS_ORCHESTRATOR=local` runs `AnalyzeCasePipeline` in the API process and keeps tests deterministic.
- `LOGAN_ANALYSIS_ORCHESTRATOR=temporal` creates the SQLAlchemy analysis run in the API, records `workflow_start` progress, and starts `AnalyzeCaseWorkflow`.
- `LOGAN_TEMPORAL_ADDRESS=temporal:7233`
- `LOGAN_TEMPORAL_NAMESPACE=default`
- `LOGAN_TEMPORAL_TASK_QUEUE=logan-analysis`
- `LOGAN_TEMPORAL_ACTIVITY_START_TO_CLOSE_SECONDS=3600`
- `LOGAN_TEMPORAL_ACTIVITY_MAX_ATTEMPTS=3`

The Temporal facade imports the SDK only when temporal orchestration is selected and raises a
typed configuration/connectivity error if the SDK or server is unavailable. Workflow history
contains only deterministic analysis inputs: case/run ids, local file paths, non-secret case
context, sanitized analysis config, and numeric activity retry/timeout settings. Database URLs,
object-store access keys, Copilot/source tokens, and source log content stay out of workflow
params.

Run a Temporal analysis worker with:

```bash
LOGAN_STORE_BACKEND=sqlalchemy \
LOGAN_DATABASE_URL=postgresql+psycopg://logan:logan@postgres:5432/logan \
LOGAN_TEMPORAL_ADDRESS=temporal:7233 \
python3 -m logan_workers.temporal_worker
```

The worker registers `AnalyzeCaseWorkflow` and `run_analysis_pipeline_activity`. The workflow
executes the activity with a stable activity id of
`{analysis_run_id}:run_analysis_pipeline`, a start-to-close timeout from
`LOGAN_TEMPORAL_ACTIVITY_START_TO_CLOSE_SECONDS`, and a retry policy from
`LOGAN_TEMPORAL_ACTIVITY_MAX_ATTEMPTS`. The activity instantiates the SQLAlchemy store from its
own process settings, loads the existing run/case, records pipeline progress into
`job_events`, updates `analysis_runs.progress_json`, completes through the same SQL fan-out and
analytics sink publish path as local SQLAlchemy runs, and marks failures with sanitized error
text before re-raising for Temporal retry/failure handling. If Temporal retries after the
database commit succeeded but before the workflow observed the result, the activity returns the
existing completed summary without rerunning the pipeline.

External analytics sinks can be enabled for SQLAlchemy-backed runs with:

- `LOGAN_ANALYTICS_SINKS_ENABLED=true`
- `LOGAN_CLICKHOUSE_URL=http://clickhouse:8123` for ClickHouse JSONEachRow inserts.
- `LOGAN_OPENSEARCH_URL=http://opensearch:9200` for OpenSearch `_bulk` indexing.
- `LOGAN_ANALYTICS_SINK_FAILURE_MODE=warn` to audit and continue on sink errors, or `fail`
  to fail the analysis run.
- `LOGAN_EXTERNAL_ANALYTICS_QUERIES_ENABLED=false` keeps report queries on SQL fan-out by
  default. Set it to `true` only when report reads should query external stores.
- `LOGAN_EXTERNAL_ANALYTICS_QUERY_TIMEOUT_SECONDS=10` controls the HTTP timeout for external
  report queries.

The adapters publish only redacted/normalized log content and derived metadata. They do not
publish raw log text, model prompts, model inputs, source tokens, or credential material.
Before ClickHouse inserts, the publisher creates the configured database plus
`enriched_log_lines` and `window_aggregates` with MergeTree schemas if needed. Before
OpenSearch bulk indexing, it creates the run-scoped `logan-logs-{case_id}-{analysis_run_id}`
index with mappings/settings and treats `resource_already_exists_exception` as success.
SQLAlchemy stores one `analytics_sink_writes` record per target write with destination,
idempotency key, payload hash, status, attempt count, row count, sanitized error, and retry
timestamps. Succeeded records skip duplicate publishes for the same run/target/payload; failed
records retry on the next completion attempt.

When `LOGAN_EXTERNAL_ANALYTICS_QUERIES_ENABLED=true`, temporal reports first query ClickHouse
`{LOGAN_CLICKHOUSE_DATABASE}.window_aggregates` only if `LOGAN_CLICKHOUSE_URL` is configured and
a succeeded `analytics_sink_writes` row exists for that case/run and destination. Log table
reports first query the run-scoped OpenSearch index only if `LOGAN_OPENSEARCH_URL` is configured
and a succeeded write exists for `{index}/_bulk`. External query failures are audited as
`analytics_query.failed` with the report name, sink name, case/run, and a sanitized error, then
the API falls back to SQL fan-out. Summary, causal graph, and causal summary reports continue
to use SQL fan-out intentionally.

Retention execution is built into both stores and can be invoked through
`POST /api/admin/retention/run`. It deletes audit logs older than
`LOGAN_AUDIT_RETENTION_DAYS`, scrubs `raw_log_lines.raw_text` and `raw_text_redacted` older than
`LOGAN_RAW_LOG_RETENTION_DAYS` to a retained marker while preserving row/evidence references,
deletes old export rows, and clears large SQLAlchemy `analysis_runs.result_json` only when the
normalized fan-out report tables remain readable. The response returns counts for deleted audits,
scrubbed raw lines, deleted exports, and cleared analysis results.

The built-in API rate limiter is disabled by default:

- `LOGAN_RATE_LIMIT_ENABLED=false`
- `LOGAN_RATE_LIMIT_REQUESTS_PER_MINUTE=120`

When enabled, it applies to `/api` routes, keys requests by hashed `logan_session` cookie when
present and by client IP otherwise, and returns JSON `429` responses with `Retry-After` when the
per-minute limit is exceeded.

## Observability

Prometheus metrics are enabled by default:

- `LOGAN_METRICS_ENABLED=true`
- `LOGAN_METRICS_PATH=/metrics`

`GET /metrics` returns Prometheus text exposition from the API process. The HTTP request
middleware records request count, duration, and in-flight gauges with only `method`, route
template, and `status_code` labels; the metrics endpoint itself is skipped. The rate limiter
records rejected requests with only `session`, `ip`, or `unknown` key type. Pipeline, Copilot
gateway, and analytics sink metrics use fixed internal labels such as step name, provider/model,
stream/status, and sink/status. Metrics do not include tokens, database URLs, S3 secrets, cookies,
raw log text, prompts, case titles/descriptions, file paths, destination names, idempotency keys,
user ids, payloads, or error messages.

Example Prometheus scrape config:

```yaml
scrape_configs:
  - job_name: logan-api
    metrics_path: /metrics
    static_configs:
      - targets: ["logan-api:8000"]
```

OpenTelemetry FastAPI tracing is optional and defaults off:

- `LOGAN_OTEL_ENABLED=false`
- `LOGAN_OTEL_SERVICE_NAME=logan-api`
- `LOGAN_OTEL_EXPORTER_OTLP_ENDPOINT=`

When enabled and the OTEL packages are installed, the API instruments FastAPI and sends spans to
the configured OTLP HTTP endpoint, for example
`http://otel-collector:4318/v1/traces`. When disabled or when OTEL imports are unavailable, the
API starts without tracing.

Run the web workspace against the local API:

```bash
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000 corepack pnpm --filter @logan/web dev
```

`NEXT_PUBLIC_API_BASE_URL` defaults to `http://localhost:8000`. The web client sends
browser requests with `credentials: "include"` for the `logan_session` cookie. The current
workbench creates cases, uploads selected log/archive files, starts analysis by
`input_file_ids`, preserves a sample/local fixture run action, lists real runs, loads report
views from API endpoints, streams case-workspace Copilot answers with fetch-based SSE parsing,
submits feedback/exports, and drives Copilot device auth start/check through the backend.

Run the full service skeleton:

```bash
docker compose up --build
```

## Remaining Staged Work

- Add step-level external artifact materialization for very large Temporal histories if pipeline
  intermediates grow beyond comfortable activity payload sizes.
- Add advanced policy groups, SCIM/user-directory sync, and richer approval workflows if enterprise
  deployments need them.
- Extend Playwright e2e coverage as richer workflows and visualizations are added.
- Consider ECharts/Cytoscape or similar libraries for richer temporal and graph visualization.

These gaps are explicitly deferred from this first foundation commit; they are not hidden behind static stubs in the tested local path.
