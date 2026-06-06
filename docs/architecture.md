# Architecture

LogAn is organized as a monorepo with three runtime surfaces:

- FastAPI backend for auth, Copilot authorization, cases, uploads, analysis runs, reports, feedback, chat, tasks, and capabilities.
- Python worker package for deterministic log analysis and Temporal workflow activities.
- Next.js web workbench for operational incident review.

The tested stage path runs synchronously:

```text
case files
  -> ingestion and sha256
  -> multi-line merge with original line refs
  -> timestamp parse, normalization, redaction
  -> Drain-style templating
  -> representative sampling
  -> GitHub Copilot Plugin annotation on redacted representatives only
  -> label broadcasting
  -> temporal aggregation
  -> candidate causal graph with temporal, PGEM-style, Granger-style, and PageRank-style evidence
  -> cautious causal summary
  -> Markdown, HTML, JSON exports
```

Each step emits `started`, `completed`, and `failed` progress events through an optional
pipeline callback. The API stores these as durable `job_events` in SQLAlchemy or in memory for
tests, and updates `analysis_runs.progress_json.current_step` plus a per-step status map as the
run advances. Event metadata is count-only, such as files, raw lines, templates, samples,
annotations, windows, causal nodes/edges, and export types; raw log text, prompt payloads,
model inputs, source tokens, and credential material are not stored in event metadata.
After each `completed` event, the API or worker process also writes a safe step-level
`step_manifest` artifact to the configured object store and upserts a row in
`analysis_step_artifacts`. Local manifests use
`.logan/object-store/cases/{case_id}/analysis-runs/{run_id}/steps/{step_name}.json` by default;
S3/MinIO manifests use
`s3://{bucket}/cases/{case_id}/analysis-runs/{run_id}/steps/{step_name}.json`. Manifest bodies
contain case/run ids, step name, artifact type, created timestamp, and sanitized completed-event
metadata only. They intentionally exclude raw log text, redacted raw text payloads, model inputs,
prompts, credentials, tokens, cookies, database URLs, S3 secrets, and full file paths.

Production adapters are represented by SQLAlchemy models, migration DDL, Docker Compose services,
and Kubernetes manifests. Metadata can run against SQLite or PostgreSQL through SQLAlchemy.
Uploaded bytes use a local disk object store by default, so tests can still inject the
deterministic in-memory store, fake device-code client, mock model gateway, and fake S3 client
with no Docker services or external model network required. Production raw uploads can switch to
S3/MinIO with `LOGAN_OBJECT_STORE_BACKEND=s3` or `minio`. Smaller files use the existing single
presigned `PUT` path. Large files use S3 multipart sessions with durable upload metadata for the
safe resume fields: upload mode, multipart upload id, part size, part count, and abort timestamp.
Completion verifies object existence and size with `head_object` without reading full object bytes.
The local object-store backend remains a direct authenticated API `PUT`.

`LOGAN_ANALYSIS_ORCHESTRATOR=local` is the default and keeps the API path synchronous. The
optional `temporal` setting creates the SQLAlchemy analysis run in the API, records workflow
start progress, and starts `AnalyzeCaseWorkflow` through a lazy Temporal client facade using
`LOGAN_TEMPORAL_ADDRESS`, `LOGAN_TEMPORAL_NAMESPACE`, and `LOGAN_TEMPORAL_TASK_QUEUE`. The
workflow is replay-safe and executes `run_analysis_pipeline_activity` with a stable activity id,
configured start-to-close timeout, and configured retry policy. The activity reads SQLAlchemy
settings from the worker process environment, records `job_events`, updates run progress, and
completes through the same normalized fan-out and optional analytics sink path as the local
SQLAlchemy run.

The SQLAlchemy completion path is also the optional external analytics sink seam. When
`LOGAN_ANALYTICS_SINKS_ENABLED=true` and sink URLs are configured, it publishes whitelisted
redacted/normalized payloads to ClickHouse and/or OpenSearch after the normalized SQL fan-out.
The publisher manages the configured ClickHouse database/tables and run-scoped OpenSearch
index mappings before writing. SQLAlchemy records each external target write in
`analytics_sink_writes` with an idempotency key and payload hash, so completed targets are
skipped on re-publish and failed targets retry on the next completion attempt. The default
remains no external sink network calls. In `warn` mode sink failures are audited and analysis
completion continues; in `fail` mode the typed sink error is allowed to fail the run after the
failed write record is preserved.

Report reads remain SQL-backed by default. When
`LOGAN_EXTERNAL_ANALYTICS_QUERIES_ENABLED=true`, the temporal report first queries ClickHouse
`window_aggregates` and the log table report first queries the run-scoped OpenSearch index,
but only when the matching service URL is configured and a succeeded `analytics_sink_writes`
record exists for that case/run. Typed external query failures are audited and fall back to the
SQL fan-out path. Summary, causal graph, and causal summary views intentionally stay on SQL
fan-out.

The web workbench renders Temporal View with Apache ECharts stacked bar time windows, including
legend, tooltip, and dataZoom browsing. Selecting a time window links to Tabular Logs with
`window_start` and `window_end` query parameters. Causal Graph renders the directed candidate
relationship graph with Cytoscape.js, preserving candidate confidence, validation state, golden
signal, and root-cause candidate cues in the graph and detail panel.

The API owns runtime injection points on app state:

- `copilot_auth_client` defaults to the real GitHub device-code client.
- `model_gateway` defaults to the real GitHub Copilot `/responses` gateway.
- `s3_client_factory` can inject fake S3/MinIO clients for presign, multipart, and `head_object`
  tests.
- tests pass deterministic fakes through `create_app(...)`.

The Copilot gateway resolves stored plugin credentials, stored GitHub source OAuth credentials, and optional server-side environment tokens. Stored source tokens are exchanged for Copilot plugin tokens, cached with `expires_at`, and revoked with the user disconnect flow; no token material crosses the frontend boundary.

## Traceability

Every pipeline object carries evidence references with:

- `case_id`
- `analysis_run_id`
- `template_id`
- `log_id`
- `file_path`
- `line_number`
- `timestamp`

Causal edges are candidate relationships only. API and worker fields use `candidate_cause`,
`confidence`, `evidence`, and `needs_validation`. The worker keeps the original temporal
precedence, lagged-correlation, service-entity, and lift signals, and now fills the PGEM and
Granger method slots with deterministic evidence instead of static extension placeholders.
PGEM-style evidence scores directed source-to-target transitions using source support, target
coverage, baseline target-rate lift, and median lag. Granger-style evidence bins offending log
templates into count series and checks whether lagged source counts improve target-count
prediction over a target-history baseline, then applies Benjamini-Hochberg adjustment across
tested directions. These scores are ranking and validation aids, not definitive root cause truth.

## Extension Seams

- Replace `StableDrainAdapter` with `drain3` behind the same `cluster()` interface.
- Add S3 object storage adapters for report artifacts.
- Add streaming Copilot `/responses` and `/api/chat/stream` SSE support.
- Add bin-size sensitivity reporting for causal methods if operators need multi-bin comparisons.
