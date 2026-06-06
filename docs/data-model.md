# Data Model

The production metadata model follows the final specification and is represented in two places:

- SQLAlchemy classes under `apps/api/app/models`.
- First-pass DDL under `apps/api/migrations/0001_initial.sql`.

Core tables:

- `users`, `sessions`, `copilot_credentials`, `copilot_device_auth`
- `cases`, `case_collaborators`
- `analysis_runs`, `job_events`, `analytics_sink_writes`
- `raw_files`, `raw_log_lines`, `normalized_log_lines`
- `log_templates`, `representative_samples`, `template_annotations`
- `time_window_signals`
- `causal_nodes`, `causal_edges`, `causal_summaries`
- `feedback`, `exports`, `audit_logs`

The API now has a durable SQLAlchemy metadata store for auth/session, Copilot credentials,
device-auth polling state, cases, uploads, analysis runs, serialized results, normalized
PostgreSQL/SQLite analytics rows, exports, feedback, and audit logs. The in-memory store
remains available as an explicit lightweight test option.

`case_collaborators` stores per-case access grants with `case_id`, `user_id`, `role`, `added_by`,
and create/update timestamps. `(case_id, user_id)` is unique. New case creators are written as
`owner` collaborators, and access checks also treat `cases.created_by` as an implicit owner so
pre-existing cases remain accessible after migration.

When an analysis completes, the SQLAlchemy store keeps the full `AnalysisResult` serialized
on `analysis_runs.result_json` with `model_inputs=[]` and also fans worker artifacts out into
the normalized analytics tables listed above. Worker file IDs are source-path deterministic,
so persisted `raw_files.id` values are generated per analysis run before raw log rows are
inserted. If `LOGAN_ANALYTICS_SINKS_ENABLED=true` and a ClickHouse or OpenSearch URL is
configured, SQLAlchemy completion can also publish redacted external analytics payloads after
the SQL fan-out and records each external target write in `analytics_sink_writes`.
SQLAlchemy-backed report endpoints read summary, temporal, log table, causal graph, and causal
summary views from normalized fan-out tables, with in-memory and missing fan-out rows falling
back to `analysis_runs.result_json`. When external analytics queries are explicitly enabled,
temporal and log table reports may read from ClickHouse/OpenSearch first, but only after the
matching succeeded `analytics_sink_writes` record proves that the run was published to that
external target.

`job_events` stores the append-only workflow progress stream for each analysis run. Events are
run-scoped by `analysis_run_id` and deduplicated by `(analysis_run_id, idempotency_key,
event_type)`, so repeated activity attempts can safely re-record the same lifecycle event.
Fields include `step_name`, `event_type`, `status`, `attempt`, sanitized count-only
`metadata`, sanitized `error_message`, and `created_at`. The API exposes these rows at
`GET /api/cases/{case_id}/analysis-runs/{run_id}/events` after enforcing that the run belongs
to the case.

`analytics_sink_writes` stores durable per-target external sink write state for SQLAlchemy
completion. Fields include `case_id`, `analysis_run_id`, `sink_name`, `destination`,
`idempotency_key`, `payload_hash`, `status`, `attempt_count`, `row_count`, sanitized
`last_error`, retry timestamps, and create/update timestamps. The table stores hashes and
metadata only; it does not store raw logs, model inputs, prompts, tokens, passwords, or full
payload bodies.

## Analytics Shape

ClickHouse and OpenSearch adapters are implemented as optional HTTP publishers. Payloads are
whitelisted from normalized result fields and include redacted/normalized messages, stable ids,
timestamps, level/service/file evidence, template ids/text, golden signals, fault categories,
entities, severity/confidence, and ingestion order. They deliberately exclude raw log text,
model inputs, model prompt payloads, and credential material. ClickHouse publishing manages
the configured database plus `enriched_log_lines` and `window_aggregates` MergeTree tables
before inserts. OpenSearch publishing manages run-scoped index creation with mappings before
bulk indexing. External report queries reuse the same configured credentials and URLs, never
run unless `LOGAN_EXTERNAL_ANALYTICS_QUERIES_ENABLED=true`, and fall back to SQL fan-out with an
`analytics_query.failed` audit record on typed query failures.

Implemented external payload targets:

- ClickHouse `enriched_log_lines` JSONEachRow rows.
- ClickHouse `window_aggregates` JSONEachRow rows.
- OpenSearch `logan-logs-{case_id}-{analysis_run_id}` `_bulk` documents with evidence refs.

Implemented external read targets:

- Temporal reports over ClickHouse `window_aggregates`.
- Log table reports over the run-scoped OpenSearch index.

Summary, causal graph, and causal summary reports intentionally continue to read the normalized
SQL fan-out tables.

Retention preserves report readability. Audit rows older than
`LOGAN_AUDIT_RETENTION_DAYS` are deleted. Raw log text older than
`LOGAN_RAW_LOG_RETENTION_DAYS` is scrubbed in-place to a retained marker while raw row ids,
normalized log rows, samples, templates, causal nodes/edges, and evidence refs are preserved.
Report retention deletes old export rows and clears `analysis_runs.result_json` only when
normalized fan-out rows remain available for the report endpoints.

Remaining production data-model work:

- External analytics store aliases/retention policy.
- Advanced policy groups or SCIM/user-directory integration if required by deployment.
