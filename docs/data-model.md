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
device-auth polling state, cases, uploads, analysis runs, serialized results, exports,
feedback, and audit logs. The in-memory store remains available as an explicit lightweight
test option. This stage intentionally keeps full `AnalysisResult` report data serialized on
`analysis_runs.result_json`; later stages can fan it out into the normalized analytics tables.

## Analytics Shape

ClickHouse and OpenSearch are included in deployment skeletons. The worker currently returns enriched log lines and window aggregates in memory. Later stages should persist these into:

- ClickHouse `enriched_log_lines`
- ClickHouse `window_aggregates`
- OpenSearch `logan-logs-{case_id}-{analysis_run_id}`
