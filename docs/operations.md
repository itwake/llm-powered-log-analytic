# Operations

## Start and stop

```bash
docker compose up -d --build
docker compose down
```

The Compose stack contains only API and web services. SQLite metadata and local files share the
`logan-data` volume. Back up that volume to preserve case data. Removing it is destructive.

For local process development:

```bash
uvicorn app.main:app --app-dir apps/api --host 0.0.0.0 --port 8000
npm run dev --workspace @logan/web
```

## Database

Run schema initialization or PostgreSQL migrations with:

```bash
python scripts/run_migrations.py
```

`LOGAN_DATABASE_URL` selects SQLite or PostgreSQL through the same SQLAlchemy implementation.

## Health and metrics

- `/healthz` — process health
- `/readyz` — application readiness
- `/metrics` — Prometheus metrics when enabled

Metrics use low-cardinality route, status, step, provider, model, and stream labels. They do not
contain request bodies, log text, credentials, filesystem paths, or user identifiers.

## Retention

Admins can run retention from the admin page or `POST /api/admin/retention/run`. Independent
settings control audit, raw-log, and report retention. Review backups before shortening them.

## Production checklist

- configure non-default secret and credential-encryption keys
- configure a real SSO provider and disable mock SSO
- configure the real model gateway and TLS verification
- use a persistent database URL and local filesystem volume
- restrict CORS and forwarded-proxy trust to the deployment topology
- monitor health, metrics, analysis failures, and disk capacity
- test database and file-volume restores
