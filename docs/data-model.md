# Data model

The database contains six application tables:

| Table | Purpose |
| --- | --- |
| `users` | Authenticated user profiles |
| `sessions` | Hashed browser session tokens |
| `llm_providers` | Per-user AI providers: type, non-secret config, encrypted credentials, models, defaults |
| `cases` | Incident context and ownership |
| `raw_files` | Uploaded file metadata and local object URI |
| `analysis_runs` | Run state, progress, compact final-result manifest, and the provider, model, and thinking level used |

An analysis result contains input-file metadata, redacted normalized log lines, templates,
samples, optional model annotations, temporal aggregates, a causal graph, and a summary. Existing
single-envelope and uncompressed result objects remain readable for compatibility.

`analysis_runs.result_json` contains a compact result manifest. Independently compressed summary,
temporal, graph, and RCA artifacts and 10,000-row log chunks live below
`LOGAN_LOCAL_OBJECT_STORE_DIR`. The artifacts exclude raw physical lines, merged raw entries, and
duplicate per-line message/template fields that report endpoints can derive from the retained
redacted result. The manifest includes aggregate log-facet counts so the default Logs page does
not scan every normalized row merely to render filters. Raw uploads remain in the same protected
object-store root.

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
