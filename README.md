# LogAn

LogAn is a focused incident log analysis application. Users create a case, upload logs, run one
analysis pipeline, and review structured logs, temporal activity, causal candidates, and a
summary.

## Stack

- FastAPI and SQLAlchemy
- SQLite
- Local filesystem uploads
- Next.js, Material UI, ECharts, and Cytoscape.js
- Optional AI providers: AI Platform and GitHub Copilot, configured per user in the app

AI is optional and configured in the web app under **AI Providers**. Each user can add AI
Platform (trust token or iB2B credentials) and GitHub Copilot (GitHub device sign-in) providers,
choose the models they offer, and set a default thinking level. When starting an analysis run or
asking analysis chat, the user picks the provider, model, and thinking level.

- A run without a provider executes the complete deterministic pipeline, including causal
  scoring and an evidence-based summary, without model calls.
- A run with a provider adds template annotation and model-generated summary text.

## Run locally

Requirements: Python 3.11+ and Node.js 22+. An OAuth-compatible SSO application is required only
when SSO is enabled.

On Windows, the local launcher creates the virtual environment, installs missing dependencies,
copies `.env.example` when needed, applies database migrations, and starts both applications:

```bat
scripts\local.bat
```

With the default `.env`, development signs in as the local default user. Set
`LOGAN_SSO_AUTHORIZE_URL`, `LOGAN_SSO_TOKEN_URL`, and `LOGAN_SSO_CLIENT_ID` to enable SSO. Use
`-ApiOnly`, `-WebOnly`, or `-SkipInstall` when only part of the startup flow is needed.

For a manual setup:

```bash
cp .env.example .env
python -m venv .venv
python -m pip install -e ".[dev]"
npm ci
```

Start the API and web app in separate terminals:

```bash
python -m alembic -c apps/api/alembic.ini upgrade head
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
Alembic migrations in `apps/api/migrations` manage the database schema.
Uploads and expanded archives are limited to 300 MiB by default. Set
`LOGAN_MAX_UPLOAD_BYTES` to another positive byte count when needed.

In development, an empty `LOGAN_SSO_AUTHORIZE_URL` uses the local default user. When the authorize
URL is set, the token URL and client id are also required and login uses SSO. Production requires
complete SSO configuration.

AI provider credentials live in the database, encrypted with a key derived from
`LOGAN_SECRET_KEY`; changing the secret invalidates stored credentials. The optional
`LOGAN_AI_PLATFORM_*` settings pre-fill the AI Platform provider form with deployment endpoints
and control transport behaviour; `LOGAN_GITHUB_COPILOT_*` settings control the GitHub transport.

## Development

```bash
python -m pytest -q
python -m ruff check apps tests scripts
npm run lint
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
