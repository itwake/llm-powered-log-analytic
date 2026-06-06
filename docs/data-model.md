# Data Model

The production metadata model follows the final specification and is represented in two places:

- SQLAlchemy classes under `apps/api/app/models`.
- First-pass DDL under `apps/api/migrations/0001_initial.sql`.

Core tables:

- `users`, `sessions`, `copilot_credentials`, `copilot_device_auth`
- `cases`, `case_collaborators`
- `analysis_runs`
- `raw_files`, `raw_log_lines`, `normalized_log_lines`
- `log_templates`, `representative_samples`, `template_annotations`
- `time_window_signals`
- `causal_nodes`, `causal_edges`, `causal_summaries`
- `feedback`, `exports`, `audit_logs`

The API now has a durable SQLAlchemy metadata store for auth/session, Copilot credentials,
device-auth polling state, cases, uploads, analysis runs, serialized results, normalized
PostgreSQL/SQLite analytics rows, exports, feedback, and audit logs. The in-memory store
remains available as an explicit lightweight test option.

When an analysis completes, the SQLAlchemy store keeps the full `AnalysisResult` serialized
on `analysis_runs.result_json` with `model_inputs=[]` and also fans worker artifacts out into
the normalized analytics tables listed above. Worker file IDs are source-path deterministic,
so persisted `raw_files.id` values are generated per analysis run before raw log rows are
inserted. Existing report API endpoints continue to read from `result_json` for this stage.

## Analytics Shape

ClickHouse and OpenSearch are included in deployment skeletons, but are still deferred. Later
stages should add:

- ClickHouse `enriched_log_lines`
- ClickHouse `window_aggregates`
- OpenSearch `logan-logs-{case_id}-{analysis_run_id}`
- External sink retry/idempotency records
- Service-backed query paths that can read from the normalized and external analytics stores
