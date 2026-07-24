# Contributing

## Setup

```bash
python -m venv .venv
# activate the environment
python -m pip install -e ".[dev]"
npm ci
python -m pytest
npm run lint
```

## Architecture rules

- `apps/web` is presentation and API-client code.
- `apps/api` owns HTTP, auth, configuration, persistence, and runtime composition.
- `logan_workers` owns analysis algorithms and must not import `app`.
- `SQLAlchemyStore` is the only persistence implementation. Tests use it through
  `create_ephemeral_store`.
- Uploads and step artifacts use the local filesystem implementation.
- Analysis runs in the API process through `AnalyzeCasePipeline`.
- `StableDrainAdapter` is the only template parser.

## Safe metadata

Raw log text, prompts, model inputs, credentials, tokens, cookies, database URLs, and full paths
must not appear in job-event metadata, step manifests, metric labels, audit metadata, benchmark
reports, or client errors. Model calls receive redacted representative samples only.

## Change checklist

- API route or schema: regenerate `docs/openapi.snapshot.json`.
- Runtime setting: update `apps/api/app/config.py`, `.env.example` when locally relevant, the root
  README, and `docker-compose.yml` when the container needs an explicit value.
- Pipeline step: update the pipeline step list, tests, progress metrics, and benchmark.
- Dependency: update `pyproject.toml` and deliberately refresh `constraints.txt`.
- UI behavior: run TypeScript checking and the relevant Playwright flow.

## Verification

```bash
python -m ruff check --select F apps tests scripts
python -m pytest
npm run lint
npm run e2e
```

`make check` runs the first three non-browser checks through the same repository entrypoints.
Tests must not make unapproved network calls. Use the mock model gateway and mock SSO provider for
deterministic local and CI behavior.
