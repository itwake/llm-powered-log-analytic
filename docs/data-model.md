# Data model

The database contains six application tables:

| Table | Purpose |
| --- | --- |
| `users` | SSO-provisioned user profiles |
| `sessions` | Hashed browser session tokens |
| `cases` | Incident context and ownership |
| `raw_files` | Uploaded file metadata and local object URI |
| `analysis_runs` | Run state, progress, configuration, and final result JSON |
| `job_events` | Ordered pipeline progress events |

An analysis result contains ingested files, normalized log lines, templates, samples, optional
model annotations, temporal aggregates, a causal graph, and a summary. It is stored once in
`analysis_runs.result_json` and validated with the `AnalysisResult` Pydantic model when read.

`apps/api/migrations/0001_initial.sql` is the PostgreSQL schema. SQLAlchemy creates the same schema
for SQLite development and tests.
