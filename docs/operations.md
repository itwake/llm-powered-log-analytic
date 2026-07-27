# Operations

## Health

`GET /healthz` verifies that the API process is running.

## Data

The default SQLite database is `.logan/logan.db`. Uploaded files are under
`.logan/object-store`. Back up both locations together. The `alembic_version` table records the
schema revision.

Apply migrations before starting a new API version:

```bash
python -m alembic -c apps/api/alembic.ini upgrade head
```

The API container runs this command before Uvicorn. A migration failure prevents the API process
from starting.

## Deployment

Production configuration requires:

- a secret key containing at least 32 characters
- SSO authorize URL, token URL, and client id
- TLS verification enabled for SSO and, when configured, AI Platform
- a persistent database and upload directory

Start one API process per instance because analysis runs use in-process background tasks.
See [Getting started](getting-started.md) for local and Docker startup instructions.

## Logs

Application logs use standard output. Analysis failures are recorded on the run and returned in a
sanitized form. Keep the process log level at `INFO` unless troubleshooting.
