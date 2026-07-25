# LogAn

LogAn is a case-based incident log diagnosis application. Engineers upload logs, run one
deterministic analysis pipeline, and inspect summary, time-window, log, causal-graph, and
causal-summary views.

The project deliberately uses one core implementation:

- Next.js web application
- FastAPI API
- SQLAlchemy persistence (SQLite by default; PostgreSQL uses the same store)
- local filesystem uploads and step artifacts
- in-process Python analysis pipeline
- deterministic `StableDrainAdapter` template parser
- Prometheus metrics

There is no separate analysis service. The API calls the analysis package directly and persists
the normalized result in SQL.

## Quick start

### Docker

```bash
docker compose up -d --build
```

Open <http://localhost:3000> and choose **Continue with SSO**. The stack stores SQLite data and
uploaded files in the `logan-data` volume.

```bash
docker compose down
```

Use `docker compose down -v` only when you intentionally want to remove local case data.

### Local development

Requirements: Python 3.11 or newer and Node.js 22 or newer.

On Windows, the helper script creates the virtual environment, installs runtime dependencies,
copies `.env.example` to `.env`, and starts both applications:

```powershell
.\scripts\local.ps1
# cmd.exe alternative: scripts\local.bat
```

For a manual or non-Windows setup:

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
python -m pip install -e ".[dev]"
npm ci
```

Copy `.env.example` values into your shell, then start the two processes:

```bash
uvicorn app.main:app --reload --app-dir apps/api --port 8000
npm run dev --workspace @logan/web
```

The default mock model provider and mock SSO flow make local development deterministic and
network-free.

## Architecture

```text
browser
  └─ Next.js
      └─ FastAPI
          ├─ SQLAlchemy ── SQLite / PostgreSQL
          ├─ local upload and artifact directory
          ├─ model gateway
          └─ AnalyzeCasePipeline
              ├─ ingest and multiline merge
              ├─ normalize and redact
              ├─ stable template clustering
              ├─ representative sampling
              ├─ annotation and label broadcast
              ├─ time-window aggregation
              ├─ causal candidate ranking
              └─ summary and exports
```

The UI name “Temporal View” means a time-window chart; it does not refer to a workflow service.

Repository layout:

- `apps/api` — FastAPI runtime, persistence, local files, model integration, and the internal
  `logan_analysis` pipeline package
- `apps/web` — Next.js workbench
- `tests` — API, engine, persistence, contract, and browser tests
- `docs` — focused architecture, API, operations, and security references

## Configuration

The copy-ready minimum is in [`.env.example`](.env.example). The current complete reference,
including defaults and production-only options, is in
[`.env.full.example`](.env.full.example). Important settings:

- `LOGAN_DATABASE_URL` — SQLAlchemy URL; defaults to `sqlite:///.logan/logan.db`
- `LOGAN_LOCAL_OBJECT_STORE_DIR` — upload and step-artifact root
- `LOGAN_LLM_PROVIDER` — `mock` for deterministic local runs or `ai_platform`
- `LOGAN_METRICS_ENABLED` — exposes low-cardinality metrics at `/metrics`
- `LOGAN_SSO_*` — SSO provider settings; the mock provider is for development only
- retention and security settings documented in `apps/api/app/config.py`

Production mode validates that runtime secrets are not left at development defaults.

## Quality checks

Run the shared local/CI checks with `make check`, or invoke them directly:

```bash
python -m pytest
python -m ruff check --select F apps tests scripts
npm run lint
npm run e2e
```

Regenerate and verify the API contract after route or schema changes:

```bash
python scripts/export_openapi.py --out docs/openapi.snapshot.json
python -m pytest tests/api/test_openapi_contract.py
```

The offline quality benchmark is also deterministic:

```bash
python -m logan_analysis.evaluation.run \
  --benchmark benchmarks/logan/checkout_incident \
  --out .logan/evaluation/report.json \
  --markdown .logan/evaluation/report.md
```

## Safety model

Raw logs are redacted before model calls. Job events and step manifests store safe counts and
identifiers rather than raw log text, prompts, credentials, or tokens. Causal edges are candidate
evidence and remain marked for validation; they are not presented as definitive root cause.

See [architecture](docs/architecture.md), [API](docs/api.md),
[operations](docs/operations.md), and [security](docs/security.md).
