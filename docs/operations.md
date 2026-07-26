# Operations

## Health and metrics

`GET /healthz` verifies that the API process is running. Prometheus metrics are served at
`GET /metrics` when `LOGAN_METRICS_ENABLED=true`.

## Data

The default SQLite database is `.logan/logan.db`. Uploaded files are under
`.logan/object-store`. Back up both locations together. PostgreSQL deployments should back up the
database and the configured local upload directory on the same schedule.

## Deployment

Production configuration requires:

- a secret key containing at least 32 characters
- SSO enabled with authorize URL, token URL, and client id
- TLS verification enabled for SSO and AI Platform
- a persistent database and upload directory

Run `python scripts/run_migrations.py` before starting a new deployment. Start the API with one
process per instance; in-process background tasks are not shared across API instances.

## Logs

Application logs use standard output. Analysis failures are recorded on the run and returned in a
sanitized form. Keep the process log level at `INFO` unless troubleshooting.
