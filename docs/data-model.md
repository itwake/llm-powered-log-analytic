# Data model

The database contains five application tables:

| Table | Purpose |
| --- | --- |
| `users` | Authenticated user profiles |
| `sessions` | Hashed browser session tokens |
| `cases` | Incident context and ownership |
| `raw_files` | Uploaded file metadata and local object URI |
| `analysis_runs` | Run state, progress, and compressed final-result envelope |

An analysis result contains input-file metadata, redacted normalized log lines, templates,
samples, optional model annotations, temporal aggregates, a causal graph, and a summary. It is
stored once in `analysis_runs.result_json` as a versioned, checksummed `zlib+base64` envelope and
validated with the `AnalysisResult` Pydantic model when read. Existing uncompressed result objects
remain readable.

The persisted result excludes raw physical lines, merged raw entries, and duplicate per-line
message/template fields that report endpoints can derive from the retained redacted result. Raw
uploads remain below `LOGAN_LOCAL_OBJECT_STORE_DIR`.

## Schema migrations

Alembic revisions in `apps/api/migrations/versions` are the source of truth for the SQLite
schema. Apply every pending revision before starting the API:

```bash
python -m alembic -c apps/api/alembic.ini upgrade head
```

After changing the SQLAlchemy models, generate and review a revision:

```bash
python -m alembic -c apps/api/alembic.ini revision --autogenerate -m "describe change"
python -m alembic -c apps/api/alembic.ini check
```

Every committed revision must define both `upgrade()` and `downgrade()`. Application startup does
not create or alter file-backed database tables.
