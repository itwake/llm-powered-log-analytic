# Architecture

LogAn is organized as a monorepo with three runtime surfaces:

- FastAPI backend for auth, Copilot authorization, cases, uploads, analysis runs, reports, feedback, chat, tasks, and capabilities.
- Python worker package for deterministic log analysis and future Temporal activities.
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
  -> candidate causal graph with evidence and PageRank-style ranking
  -> cautious causal summary
  -> Markdown, HTML, JSON exports
```

Each step emits `started`, `completed`, and `failed` progress events through an optional
pipeline callback. The API stores these as durable `job_events` in SQLAlchemy or in memory for
tests, and updates `analysis_runs.progress_json.current_step` plus a per-step status map as the
run advances. Event metadata is count-only, such as files, raw lines, templates, samples,
annotations, windows, causal nodes/edges, and export types; raw log text, prompt payloads,
model inputs, source tokens, and credential material are not stored in event metadata.

Production adapters are represented by SQLAlchemy models, migration DDL, Docker Compose services, and Kubernetes manifests. Metadata can run against SQLite or PostgreSQL through SQLAlchemy. Uploaded bytes use a local disk object store by default, so tests can still inject the deterministic in-memory store, fake device-code client, mock model gateway, and fake S3 client with no Docker services or external model network required. Production uploads can switch to S3/MinIO presigned `PUT` URLs with `LOGAN_OBJECT_STORE_BACKEND=s3` or `minio`; completion verifies object existence and size with `head_object` without reading full object bytes.

`LOGAN_ANALYSIS_ORCHESTRATOR=local` is the default and keeps the API path synchronous. The
optional `temporal` setting starts `AnalyzeCaseWorkflow` through a lazy Temporal client facade
using `LOGAN_TEMPORAL_ADDRESS`, `LOGAN_TEMPORAL_NAMESPACE`, and
`LOGAN_TEMPORAL_TASK_QUEUE`. The workflow class remains locally runnable and accepts
`case_context` and `config`, but real Temporal activities with durable retries are still an
extension seam.

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

The API owns runtime injection points on app state:

- `copilot_auth_client` defaults to the real GitHub device-code client.
- `model_gateway` defaults to the real GitHub Copilot `/responses` gateway.
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

Causal edges are candidate relationships only. API and worker fields use `candidate_cause`, `confidence`, `evidence`, and `needs_validation`.

## Extension Seams

- Replace `StableDrainAdapter` with `drain3` behind the same `cluster()` interface.
- Extend the ClickHouse/OpenSearch sink adapters with service-backed query paths.
- Add S3 object storage adapters for report artifacts.
- Add resumable/multipart S3 uploads for large files and interrupted browser sessions.
- Replace the Temporal facade placeholder with replay-safe workflow activities and durable retry
  state.
- Add streaming Copilot `/responses` and `/api/chat/stream` SSE support.
- Extend causal methods with PGEM and Granger implementations while retaining bin-size sensitivity checks.
