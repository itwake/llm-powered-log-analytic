# LogAn

LogAn is a focused incident log analysis application. Users sign in with SSO, create a case,
upload logs, run one analysis pipeline, and review structured logs, temporal activity, causal
candidates, and a summary.

## Stack

- FastAPI and SQLAlchemy
- SQLite
- Local filesystem uploads
- Next.js and Material UI
- Optional AI Platform integration

`LOGAN_LLM_PROVIDER` has two valid values:

- `none` runs the complete deterministic pipeline, including causal scoring and an
  evidence-based summary, without model calls.
- `ai_platform` adds template annotation, model-generated summary text, and case chat.

## Run locally

Requirements: Python 3.11+, Node.js 22+, and an OAuth-compatible SSO application.

```bash
cp .env.example .env
python -m venv .venv
python -m pip install -e ".[dev]"
npm ci
```

Configure the SSO values in `.env`, then start the API and web app in separate terminals:

```bash
python -m uvicorn app.main:app --reload --env-file .env --app-dir apps/api --host 127.0.0.1 --port 8000
npm run dev --workspace @logan/web
```

Open `http://localhost:3000`.

Docker uses the same `.env` file:

```bash
docker compose up --build
```

## Configuration

Copy `.env.example` for the minimum setup or `.env.full.example` for every supported setting.
The API reads `.env` at startup through the local command above. The web app uses
`NEXT_PUBLIC_API_BASE_URL` at build time and defaults to `http://localhost:8000`.

SQLite data and uploaded files are stored under `.logan/` by default. Set
`LOGAN_DATABASE_PATH` and `LOGAN_LOCAL_OBJECT_STORE_DIR` to use other local paths.

## Development

```bash
python -m pytest -q
python -m ruff check apps tests scripts
npm run typecheck
npm run build
```

Generate the checked-in API contract after changing routes or schemas:

```bash
python scripts/export_openapi.py --out docs/openapi.snapshot.json
```

## Documentation

- [Getting started](docs/getting-started.md)
- [User guide](docs/user-guide.md)
- [Architecture](docs/architecture.md)
- [Analysis pipeline](docs/analysis-pipeline.md)
- [Reliability and explainability](docs/reliability-and-explainability.md)
- [Glossary](docs/glossary.md)
- [API](docs/api.md)
- [Data model](docs/data-model.md)
- [Operations](docs/operations.md)
- [Security](docs/security.md)
