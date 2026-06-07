# Operations

## Local

Run Python tests without external services:

```bash
python3 -m pytest tests
```

## Offline Benchmark Evaluation

The repository includes a deterministic LogAn-style checkout incident benchmark under
`benchmarks/logan/checkout_incident`. The benchmark reuses the synthetic fixture logs from
`tests/fixtures/logs/checkout_incident` and labels expected template patterns, golden signals,
fault categories, key entities, root-cause candidates, useful causal edges, and summary rubric
requirements.

Run the benchmark locally with Python 3.11+:

```bash
python -m logan_workers.evaluation.run \
  --benchmark benchmarks/logan/checkout_incident \
  --out .logan/evaluation/report.json \
  --markdown .logan/evaluation/report.md
```

The equivalent Make target is:

```bash
make PYTHON=.venv/bin/python evaluate
```

The evaluator runs `AnalyzeCasePipeline` with `MockCopilotAnnotationGateway`, so it does not
require Docker, Temporal, GitHub Copilot credentials, or external network access. It emits
thresholded metrics for review-load reduction, golden-signal macro F1, fault-category micro and
macro F1, entity precision/recall/F1, root-cause hit@k, useful causal-edge recall, and summary
rubric quality.

Benchmark reports are intentionally compact. They include counts, metric details, label pattern
ids, canonical expected regex patterns, template ids, edge ids, and summary rubric term coverage.
They do not include source log bodies, raw message fields, model inputs, representative-line text,
or absolute fixture paths. Report rendering fails closed if sensitive auth terms, prompt/raw fields,
or absolute paths are detected in the JSON or Markdown output.

For CI or staging, run the benchmark after unit tests and before deploying worker changes:

```bash
python -m pytest -q
python -m logan_workers.evaluation.run \
  --benchmark benchmarks/logan/checkout_incident \
  --out .logan/evaluation/report.json \
  --markdown .logan/evaluation/report.md
```

Treat a non-zero exit code as a release blocker for changes that alter parsing, templating,
annotation, causal graph ranking, or summary generation. Store the JSON report as a CI artifact
for score trend review; the Markdown file is intended for quick human inspection in staging.

## Synthetic Scale Benchmark

Use the scale benchmark when validating worker ingestion and pipeline behavior on larger generated
inputs. The runner creates deterministic synthetic checkout incident logs under
`.logan/scale-fixtures`, which is ignored by git, then runs the real `AnalyzeCasePipeline` with
`MockCopilotAnnotationGateway`.

The generated fixture mixes:

- plain `.log` input
- `.jsonl` input
- `.log.gz` input
- `.zip` input containing both plain and JSONL members
- cross-service dependency failures, retries, resource saturation, gateway failures, and multiline
  stack traces

Run the default quick profile:

```bash
make PYTHON=.venv/bin/python scale-benchmark
```

The quick profile targets 64 KiB of logical uncompressed log payload by default. To keep a local run
smaller or larger while preserving the same mixed-format shape:

```bash
make PYTHON=.venv/bin/python scale-benchmark SCALE_PROFILE=quick SCALE_TARGET_BYTES=67108864
```

Run the 1 GiB profile on a worker host with enough memory for the current in-memory pipeline:

```bash
make PYTHON=.venv/bin/python scale-benchmark SCALE_PROFILE=1gb
```

Run the 5 GiB profile only on a dedicated benchmark host:

```bash
make PYTHON=.venv/bin/python scale-benchmark SCALE_PROFILE=5gb
```

Profile sizes are logical uncompressed payload sizes. The on-disk fixture can be smaller because
the gzip and zip portions are compressed. The JSON report is written to
`.logan/evaluation/scale-{profile}.json`; the Markdown summary is written to
`.logan/evaluation/scale-{profile}.md`.

Scale reports include generated fixture size, input file count, raw line count, ingested file
count, source entries, normalized logs, templates, representative samples, annotations, time
windows, causal nodes and edges, wall time, Linux peak RSS when available, model call count,
annotation model call count, Causal Summary model call count, review-load reduction, and Causal
Summary presence/confidence/counts. They intentionally omit raw log bodies, local absolute paths,
prompt/model input payloads, credentials, tokens, secrets, and passwords. Report rendering fails
closed if those leak-shaped fields or terms appear in JSON or Markdown.

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

## Full-Stack Docker Smoke

Use the compose stack when validating the production-shaped path:

```bash
docker compose config
make full-stack-smoke
make full-stack-down
```

`make full-stack-smoke` first runs `make full-stack-up`, then executes the profiled `smoke`
service. The stack starts PostgreSQL, MinIO plus a bucket-init container, ClickHouse,
OpenSearch, Temporal, the FastAPI API, and the Temporal worker. API and worker share the same
SQLAlchemy/PostgreSQL store, use `LOGAN_OBJECT_STORE_BACKEND=minio`, start analysis through
`LOGAN_ANALYSIS_ORCHESTRATOR=temporal`, publish external analytics with
`LOGAN_ANALYTICS_SINKS_ENABLED=true`, read temporal/log reports with
`LOGAN_EXTERNAL_ANALYTICS_QUERIES_ENABLED=true`, and set `LOGAN_LLM_PROVIDER=mock` so the smoke
never needs Copilot credentials.

The runner in `scripts/full_stack_smoke.py` validates the following:

- API health, user registration/login, and case creation.
- MinIO presigned single-part upload for all checkout incident fixture logs.
- MinIO `head_object` confirms object existence and size before upload completion.
- Analysis starts with `input_file_ids`, then a Temporal worker materializes `s3://` inputs,
  runs the pipeline, and cleans temporary materialized files.
- Summary, temporal, logs, causal graph, and causal summary report endpoints return non-empty
  results.
- Job events include `materialize_inputs` and every pipeline step, with sanitized metadata only.
- Step artifact manifests are created without raw logs, local materialized paths, presigned query
  strings, credentials, tokens, prompts, or model inputs.
- ClickHouse contains run rows in `logan.enriched_log_lines` and `logan.window_aggregates`.
- OpenSearch contains run documents in the run-scoped `logan-logs-{case_id}-{run_id}` index.
- PostgreSQL `analytics_sink_writes` has succeeded ClickHouse/OpenSearch writes, and
  `analytics_query.external` audit rows confirm the API report calls used external stores.

From the host, the script defaults to `localhost` service ports. Inside compose, the `smoke`
service uses container DNS names. If you run the script manually from the host while the API is
configured with `LOGAN_S3_ENDPOINT=http://minio:9000`, set:

```bash
LOGAN_FULL_STACK_S3_PUBLIC_ENDPOINT=http://localhost:9000 python3 scripts/full_stack_smoke.py
```

The default exposed ports are API `8000`, web `3000`, PostgreSQL `5432`, MinIO `9000/9001`,
ClickHouse `8123/9002`, OpenSearch `9200`, Redis `6379`, and Temporal `7233`. Override with the
`LOGAN_*_PORT` variables in `docker-compose.yml` if a VM already uses those ports.

OpenSearch is capped at `-Xms512m -Xmx512m` in compose. On small VMs, leave several GiB free for
Docker or lower other local workloads before running the smoke. The compose credentials are local
development placeholders only. Do not put real Copilot, GitHub, S3, database, or customer
credentials into `.env`, compose files, or committed docs.

PostgreSQL startup runs idempotent SQL migrations after SQLAlchemy creates the current metadata
shape. Applied migrations are recorded in `schema_migrations` with version, checksum, status,
duration, and timestamps, guarded by a PostgreSQL advisory lock so concurrent API replicas do not
race the same migration. A checksum change or previously failed migration is treated as an
operator-review condition rather than being retried blindly.

Run the same migration path explicitly with:

```bash
make migrate
```

The command calls `scripts/run_migrations.py`. It creates the SQLAlchemy schema for SQLite and
PostgreSQL stores, applies PostgreSQL incremental SQL migrations with `schema_migrations`
tracking, and exits as a no-op for the explicit in-memory store.

The pytest wrapper is opt-in:

```bash
LOGAN_RUN_FULL_STACK_SMOKE=true python3 -m pytest -q tests/integration/test_full_stack_smoke.py
```

`make temporal-retry-smoke` runs an opt-in Temporal test-server smoke. It starts a real Temporal
test environment, registers `AnalyzeCaseWorkflow`, intentionally fails the first
`run_analysis_pipeline_activity` attempt, verifies Temporal retries and completes the real Logan
activity on the second attempt, then invokes the activity again to confirm idempotent completion
does not duplicate job events or fan-out rows. It is skipped in normal pytest runs unless
`LOGAN_RUN_TEMPORAL_INTEGRATION=true` is set.

`make copilot-staging-smoke` runs the real Copilot `/responses` annotation smoke. It is skipped
unless `LOGAN_RUN_COPILOT_STAGING_SMOKE=true` and either `LOGAN_GITHUB_COPILOT_TOKEN` or
`LOGAN_GITHUB_SOURCE_TOKEN` is present. Full-stack smoke always uses the mock provider instead.

Run the API locally:

```bash
uvicorn app.main:app --reload --app-dir apps/api
```

By default the API uses the lightweight in-memory store unless a database URL is configured.
Set `LOGAN_DATABASE_URL=sqlite:////tmp/logan.db` for local durable metadata, or use a
PostgreSQL URL such as `postgresql+psycopg://logan:logan@postgres:5432/logan`.
`LOGAN_STORE_BACKEND=auto` selects SQLAlchemy when `LOGAN_DATABASE_URL` is set; `memory`
and `sqlalchemy` force a backend explicitly.
Set `LOGAN_CORS_ALLOWED_ORIGINS` to a comma-separated list of browser origins allowed to send
credentialed API requests. The default is `http://localhost:3000`; production deployments should
set it to the deployed web origin, such as `https://logan.example.com`.
Containerized API deployments can set `LOGAN_API_WORKERS` to control the number of Uvicorn worker
processes. Keep it low for local smoke runs and size it from CPU limits in Kubernetes.

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
size. Completed S3-backed `input_file_ids` are accepted for analysis: the local API orchestrator
or Temporal worker downloads each `s3://` object into `LOGAN_ANALYSIS_INPUT_TMP_DIR` (default
`.logan/analysis-inputs`) immediately before pipeline ingestion and deletes the temporary files
after the pipeline call exits.

Large S3/MinIO raw uploads use multipart/resumable sessions when the client asks with
`multipart=true` or when the declared size reaches `LOGAN_S3_MULTIPART_THRESHOLD_BYTES`
(default `104857600`, 100 MiB). `LOGAN_S3_MULTIPART_PART_SIZE_BYTES` defaults to `67108864`
(64 MiB), and `LOGAN_S3_MULTIPART_MAX_PARTS` defaults to `10000`. Multipart session metadata is
stored on the upload record with safe fields such as upload mode, S3 upload id, part size, part
count, and abort timestamp; raw bytes, log content, credentials, and source tokens are never stored
there. Clients can resume with `GET /api/cases/{case_id}/uploads/{file_id}/multipart`, which
returns fresh part URLs and S3 `list_parts` data, or abort with `DELETE` on the same route. The
local backend intentionally remains a direct authenticated API `PUT`.

Step artifact manifests use the same object-store backend:

- `LOGAN_STEP_ARTIFACTS_ENABLED=true`
- `LOGAN_STEP_ARTIFACT_FAILURE_MODE=warn`, or `fail` to fail analysis when manifest storage fails.

Each completed pipeline step writes a small `step_manifest` JSON object and upserts
`analysis_step_artifacts` by `(analysis_run_id, step_name, artifact_type)`. Local manifests are
stored under
`.logan/object-store/cases/{case_id}/analysis-runs/{run_id}/steps/{step_name}.json`; S3/MinIO
manifests are stored under
`s3://{bucket}/cases/{case_id}/analysis-runs/{run_id}/steps/{step_name}.json`. Manifest bodies
contain only case/run ids, step name, artifact type, timestamp, and sanitized completed-event
metadata. They do not include raw log text, `raw_text_redacted`, model prompts, model inputs,
credentials, tokens, cookies, database URLs, S3 secrets, or full file paths. In `warn` mode,
storage errors are audited with a sanitized `artifact_error` and analysis continues.

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
run, event, artifact, report, log, and chat context views but cannot mutate analysis/upload state. Read
routes hide inaccessible cases with `404`; mutating routes return `403` when the case exists but
the caller lacks the required role.

Admin-only routes live under `/api/admin`:

- `GET /api/admin/users`
- `PATCH /api/admin/users/{user_id}` for role and active-state changes
- `GET /api/admin/audit-logs`
- `GET /api/admin/settings`
- `POST /api/admin/retention/run`

Audit logs include case access, raw log search, export creation, feedback submission, analysis
completion, and `model.invocation`. Model invocation audit metadata is intentionally limited to
the analysis run id, model provider/name/reasoning effort, prompt version, representative sample
or model-input counts, annotation/template counts, and `redacted: true`. Raw or redacted log
lines, prompt bodies, model input payloads, representative line text, tokens, credentials, secrets,
and local or fixture file paths must not be stored in audit metadata.

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
contains only deterministic analysis inputs: case/run ids, local file paths or `s3://` object
URIs, non-secret case context, sanitized analysis config, and numeric activity retry/timeout
settings. Database URLs, object-store access keys, Copilot/source tokens, and source log content
stay out of workflow params. S3-backed inputs are materialized inside
`run_analysis_pipeline_activity`, so the API process does not download objects for Temporal runs.

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
own process settings, loads the existing run/case, materializes any `s3://` input objects with the
worker's S3/MinIO credentials, records pipeline progress into `job_events`, writes/upserts step
artifact manifests after completed events, updates `analysis_runs.progress_json`, completes through
the same SQL fan-out and analytics sink publish path as local SQLAlchemy runs, and marks failures
with sanitized error text before re-raising for Temporal retry/failure handling. If Temporal
retries after the database commit succeeded but before the workflow observed the result, the
activity returns the existing completed summary without rerunning the pipeline.

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
the API falls back to SQL fan-out. Successful external query reads are audited as
`analytics_query.external` with only the report name, sink name, case id, and run id. Summary,
causal graph, and causal summary reports continue to use SQL fan-out intentionally.

Causal summaries are evidence-first and LLM-backed. The worker builds a structured evidence packet
from the causal graph, redacted normalized logs, template text, and safe case context, then calls
the model gateway with `metadata.purpose=causal_summary`. Summary packets do not include raw log
text, model input history, prompt payloads, tokens, passwords, API keys, or secret material. The
allowed log evidence surface is redacted message text, template text, line number, log id,
template id, service, time, confidence, and method. Generated summaries include internal RCA
markdown, customer-safe markdown, evidence claims, evidence refs, next validation steps,
uncertainties, confidence, and structured details. If the gateway is unavailable or the model
output fails schema/evidence validation, the worker emits a cautious evidence-based fallback that
uses candidate and needs-validation language for source signals, downstream symptoms, affected
services, and dependency/resource signals present in the packet.

Causal summaries are editable by case owners, editors, and global engineer/admin users through
`PATCH /api/cases/{case_id}/analysis-runs/{run_id}/causal-summary`. The edit updates only the
summary markdown and customer-safe update; graph evidence refs, evidence claims, uncertainties,
confidence, and next actions stay attached to the generated evidence. SQLAlchemy stores the edit in
`causal_summaries` and, when available, mirrors it into
`analysis_runs.result_json.causal_summary` and regenerated export content. Audit events use
`causal_summary.edit` and include only lengths/counts plus ids, not raw logs, prompts, token
material, or secrets. Markdown, HTML, and JSON causal-summary exports are generated from the
current edited summary; when retention has cleared `result_json`, the API uses the retained SQL
fan-out summary row for causal-summary-only exports.

Retention execution is built into both stores and can be invoked through
`POST /api/admin/retention/run`. It deletes audit logs older than
`LOGAN_AUDIT_RETENTION_DAYS`, scrubs `raw_log_lines.raw_text` and `raw_text_redacted` older than
`LOGAN_RAW_LOG_RETENTION_DAYS` to a retained marker while preserving row/evidence references,
deletes old export rows, and clears large SQLAlchemy `analysis_runs.result_json` only when the
normalized fan-out report tables remain readable. The response returns counts for deleted audits,
scrubbed raw lines, deleted exports, deleted step artifact rows, and cleared analysis results.
Local step artifact object deletion is best-effort and never exposes filesystem paths or secrets
through the API response.

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
views from API endpoints, renders Temporal View with Apache ECharts, renders Causal Graph with
Cytoscape.js, streams case-workspace Copilot answers with fetch-based SSE parsing, submits
feedback/exports, and drives Copilot device auth start/check through the backend.

Run the full service skeleton:

```bash
docker compose up --build
```

## Remaining Staged Work

- Add advanced policy groups, SCIM/user-directory sync, and richer approval workflows if enterprise
  deployments need them.
- Extend Playwright e2e coverage as richer workflows and visualizations are added.

These gaps are explicitly deferred from this first foundation commit; they are not hidden behind static stubs in the tested local path.
