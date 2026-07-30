# Architecture

LogAn has two deployable applications:

- `apps/api`: FastAPI routes, SQL persistence, local file storage, and the analysis package.
- `apps/web`: the Next.js user interface.

See [Analysis pipeline](analysis-pipeline.md) for the processing and persistence contract.

The API owns background analysis tasks. A run follows one ordered pipeline:

1. ingest uploaded files
2. merge multiline entries
3. parse and redact
4. extract templates
5. select representative samples
6. annotate templates when AI Platform is enabled
7. broadcast annotations to log lines
8. aggregate temporal activity
9. score causal candidates
10. render the incident summary

Run progress and the final `AnalysisResult` are persisted by the same API process. CPU-bound
pipeline activities and final-result encoding run on worker threads so they do not block the API
event loop. The compressed result envelope is the source for every report endpoint, so report
reads do not maintain a second analytical schema.

Uploaded files use `file://` object URIs rooted at `LOGAN_LOCAL_OBJECT_STORE_DIR`. Metadata and
analysis results use the SQLite database at `LOGAN_DATABASE_PATH`. Alembic owns the database
schema and applies ordered revisions before the API process starts.

The browser authenticates with an HTTP-only session cookie. The login endpoint either starts the
configured SSO flow or signs in the development default user. The web application sends API
requests directly to `NEXT_PUBLIC_API_BASE_URL`.
