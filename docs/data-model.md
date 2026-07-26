# Data model

The database contains five application tables:

| Table | Purpose |
| --- | --- |
| `users` | SSO-provisioned user profiles |
| `sessions` | Hashed browser session tokens |
| `cases` | Incident context and ownership |
| `raw_files` | Uploaded file metadata and local object URI |
| `analysis_runs` | Run state, progress, and final result JSON |

An analysis result contains ingested files, normalized log lines, templates, samples, optional
model annotations, temporal aggregates, a causal graph, and a summary. It is stored once in
`analysis_runs.result_json` and validated with the `AnalysisResult` Pydantic model when read.

SQLAlchemy creates the SQLite schema when the API starts.
