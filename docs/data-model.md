# Data Model

The production metadata model follows the final specification and is represented in two places:

- SQLAlchemy classes under `apps/api/app/models`.
- First-pass DDL under `apps/api/migrations/0001_initial.sql`.

Core tables:

- `users`, `sessions`, `copilot_credentials`
- `cases`, `case_collaborators`
- `analysis_runs`
- `raw_files`, `raw_log_lines`, `normalized_log_lines`
- `log_templates`, `representative_samples`, `template_annotations`
- `time_window_signals`
- `causal_nodes`, `causal_edges`, `causal_summaries`
- `feedback`, `exports`, `audit_logs`

The stage store is in-memory for testability, but the same identifiers and evidence references are used by API responses and exports.

## Analytics Shape

ClickHouse and OpenSearch are included in deployment skeletons. The worker currently returns enriched log lines and window aggregates in memory. Later stages should persist these into:

- ClickHouse `enriched_log_lines`
- ClickHouse `window_aggregates`
- OpenSearch `logan-logs-{case_id}-{analysis_run_id}`
