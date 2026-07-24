# LogAn repository guide

LogAn is a Next.js workbench backed by FastAPI, SQLAlchemy, a local file store, and an in-process
Python analysis pipeline.

## Commands

```bash
python -m pytest
python -m ruff check apps tests scripts
npm run lint
python scripts/export_openapi.py --out docs/openapi.snapshot.json
docker compose up -d --build
```

## Hard rules

- Preserve raw-log redaction before model calls.
- Do not place raw logs, prompts, credentials, tokens, database URLs, or paths in safe metadata.
- Keep one SQLAlchemy store, one local file path, one in-process pipeline, and one stable template
  parser.
- Treat causal relationships as candidate evidence requiring validation.
- Regenerate the OpenAPI snapshot after route or schema changes.
- Update pipeline step lists and tests together.
- Keep local and CI behavior deterministic with the mock model gateway and mock SSO provider.

See `README.md`, `CONTRIBUTING.md`, and `docs/architecture.md`.
