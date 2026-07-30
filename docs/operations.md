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

New analysis results are partitioned into report-specific compressed artifacts. Summary, Timeline,
Graph, RCA, and chat do not load log rows. An unfiltered Logs request reads only the chunks for its
requested page. Filters and free-text searches currently scan all log chunks, but validate them
one at a time so memory use remains bounded. Results created by older application versions retain
the single-envelope format and use a five-minute decoded-result compatibility cache.

Each result artifact is written to a unique temporary file and atomically moved into place.
Configured result roots are resolved to absolute paths, and temporary filenames contain only a
full 128-bit random identifier plus the `.part` suffix. Avoiding a second copy of the artifact name
keeps temporary search-index paths below the legacy Windows path-length boundary when the final
artifact path itself is valid.

Run the repeatable report-path benchmark with a chunked two-million-row synthetic result:

```bash
python scripts/benchmark_report_api.py --records 2000000
```

The benchmark creates its database and object-store artifacts in a temporary directory, calls the
actual analysis-run and report routes, and validates the response bodies rather than treating an
HTTP 200 response as sufficient. The checks cover run progress, summary reduction counts,
timeline totals, first and last log pages, redacted log messages, graph references, and RCA
evidence. It prints per-route latency, process working-set measurements, body metrics, and every
body check; any failed body check makes the command exit non-zero. It then disposes the database
connection and removes the temporary data.

## Logs

Application logs use standard output. Analysis failures are recorded on the run and returned in a
sanitized form. A failed background task logs its run identifier, exception type, numeric OS error
code when available, and a bounded call chain containing function names and line numbers only.
The run progress also retains `failed_step`, `error_type`, and `error_code` when available. Full
filesystem paths, uploaded filenames, log content, and exception source lines are excluded from
these diagnostics. Keep the process log level at `INFO` unless troubleshooting.
