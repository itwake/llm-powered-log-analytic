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

Development uses the local default user when `LOGAN_SSO_AUTHORIZE_URL` is empty. Non-development
deployments require complete SSO configuration.

Start one API process per instance because analysis runs use in-process background tasks.
See [Getting started](getting-started.md) for local and Docker startup instructions.

An abrupt process exit cannot resume an in-memory analysis task. On the next API startup, any
persisted `queued` or `processing` run is marked `failed` with an interruption message so cases do
not remain indefinitely stuck in an active state. The user can then start a new run with the
already completed uploads.

## Logs

Application logs use standard output. Analysis failures are recorded on the run and returned in a
sanitized form. Keep the process log level at `INFO` unless troubleshooting.
