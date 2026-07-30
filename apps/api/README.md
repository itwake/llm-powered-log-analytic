# LogAn API

`apps/api` is the backend application for LogAn. It owns authentication, case and upload
management, SQLite persistence, background analysis runs, report APIs, and optional AI Platform
integration. The analysis package is deployed with the API and does not depend on FastAPI or the
database layer.

Start with the repository [README](../../README.md), [contribution guide](../../CONTRIBUTING.md),
and [architecture](../../docs/architecture.md) for the complete system context.

## Responsibilities

The API is responsible for:

- creating browser sessions through the configured authentication mode;
- enforcing case ownership on every case, upload, run, report, and chat request;
- storing application metadata and completed analysis results in SQLite;
- storing uploaded files below the configured local object-store directory;
- starting and cancelling analysis tasks in the API process;
- exposing the five report views from one validated `AnalysisResult`;
- calling AI Platform when `LOGAN_LLM_PROVIDER=ai_platform`;
- serving `/healthz` and the OpenAPI document.

## Technology

- Python 3.11 or newer
- FastAPI, Starlette, and Uvicorn
- Pydantic v2
- SQLAlchemy 2 and SQLite
- Alembic
- HTTPX
- pytest, pytest-asyncio, and Ruff

The root `pyproject.toml` defines the `logan-platform` distribution. Both import packages are below
`apps/api`, so commands run from the repository root use `--app-dir apps/api` or the configured
pytest Python path.

## Directory layout

```text
apps/api/
├── alembic.ini
├── app/
│   ├── main.py                    # application factory, middleware, routers, lifespan
│   ├── config.py                  # LOGAN_* settings and runtime validation
│   ├── dependencies.py            # store, model gateway, user, and ownership dependencies
│   ├── records.py                 # persistence-facing record types and error sanitization
│   ├── sqlalchemy_store.py        # the application metadata store and run execution
│   ├── store.py                   # store construction and public exports
│   ├── api/
│   │   ├── auth.py                # login, SSO callback, session lookup, logout
│   │   ├── cases.py               # cases, local uploads, analysis runs, cancellation
│   │   ├── reports.py             # summary, temporal, logs, graph, causal summary
│   │   └── chat.py                # evidence-bound AI chat over SSE
│   ├── schemas/                   # Pydantic request and response models
│   ├── models/tables.py           # SQLAlchemy table definitions
│   ├── core/security.py           # session token issue and hashing
│   └── services/
│       ├── object_store.py        # generated local paths, file URIs, checksums
│       ├── sso_auth_service.py    # OAuth authorize, token exchange, user provisioning
│       ├── model_gateway.py       # shared model-gateway errors and helpers
│       ├── model_gateway_factory.py
│       └── aiplatform_model_gateway.py
├── logan_analysis/
│   ├── models.py                  # validated analysis-domain models
│   ├── ports.py                   # model-gateway protocol
│   ├── pipeline.py                # ordered analysis pipeline
│   ├── activities/                # individual pipeline operations
│   ├── algorithms/                # parsing, redaction, templates, sampling
│   └── prompts/                   # AI annotation and summary instructions
└── migrations/
    ├── env.py
    └── versions/                  # ordered Alembic revisions
```

## Runtime architecture

### Application composition

`app.main.create_app()` validates settings, constructs the `SQLAlchemyStore`, configures logging,
selects the model gateway, installs credentialed CORS, and registers four routers. Tests can inject
a store or a `ModelGateway`; normal runtime uses the configured implementations.

Analysis runs are `asyncio` tasks tracked on `app.state.analysis_tasks`. Cancelling a run or
deleting its case cancels the matching task. Application shutdown cancels any remaining tasks and
closes the model gateway.

This deployment model assumes one API process per instance. Task ownership and cancellation are
process-local.

### Authentication and ownership

The browser begins authentication at `GET /api/auth/login`.

- In development, an empty `LOGAN_SSO_AUTHORIZE_URL` creates or reuses the `Local User` profile.
- When `LOGAN_SSO_AUTHORIZE_URL` is set, the token URL and client id are required and login starts
  the OAuth authorization-code flow.
- Non-development environments require complete SSO configuration.

The API stores only the SHA-256 hash of the random `logan_session` token. Browser cookies are
HTTP-only, same-site, and secure in production. `current_user` resolves the session and
`require_case_owner` returns `404` for cases the user does not own, so case existence is not
disclosed.

### Persistence and files

`SQLAlchemyStore` is the single metadata implementation. It stores five tables:

| Table | Content |
| --- | --- |
| `users` | authenticated user profiles |
| `sessions` | hashed browser sessions and expiry |
| `cases` | incident context, status, and owner |
| `raw_files` | upload metadata, local file URI, checksum |
| `analysis_runs` | run state, progress, model selection, final result JSON |

Alembic revisions are the database schema source of truth. File-backed application startup does
not create or alter tables automatically.

Uploads are written below `LOGAN_LOCAL_OBJECT_STORE_DIR` using generated case and file ids plus a
sanitized filename. The API verifies the declared size and records a SHA-256 checksum. A file and
its expanded archive content are each limited to 300 MiB by default. `LOGAN_MAX_UPLOAD_BYTES`
changes both limits. Analysis resolves only completed upload ids; clients cannot submit arbitrary
server paths.

### Analysis execution

`logan_analysis.pipeline.AnalyzeCasePipeline` runs these steps in order:

1. `ingest_paths`
2. `merge_entries`
3. `preprocess_redact`
4. `template_extraction`
5. `representative_sampling`
6. `ai_platform_annotation`
7. `broadcast_annotations`
8. `temporal_aggregation`
9. `causal_graph`
10. `causal_summary`

Progress snapshots contain generated counts and sanitized failures. A successful run stores one
validated `AnalysisResult`; every report endpoint reads that result. The analysis package retains
evidence identifiers and source lines through transformations. Causal edges remain investigation
candidates rather than proof.

`LOGAN_LLM_PROVIDER=none` skips model annotation and produces a deterministic evidence summary.
`LOGAN_LLM_PROVIDER=ai_platform` enables template annotation, generated summary text, and completed
run chat. Model input is limited to redacted representative samples or bounded evidence context.

### Case and run lifecycle

A case is the ownership and incident-context boundary. It moves through `created`, `uploading`,
`analyzing`, `completed`, `failed`, or `cancelled` as files and runs change. Deleting a case marks
it deleted and removes it from normal access.

A case can have multiple numbered analysis runs. Each run moves through `queued`, `processing`,
`completed`, `failed`, or `cancelled` and retains its own progress and final result. Report URLs
always include the run id, so historical results remain separate.

## HTTP surface

All application routes are under `/api`; `/healthz` is the process health endpoint.

| Area | Routes |
| --- | --- |
| Authentication | `/api/auth/login`, `/api/auth/sso/callback`, `/api/auth/me`, `/api/auth/logout` |
| Cases | list, create, read, update, and delete under `/api/cases` |
| Uploads | create upload metadata and PUT content under a case |
| Runs | start, list, read, and cancel analysis runs under a case |
| Reports | summary, temporal, logs, causal graph, and causal summary per run |
| Chat | `POST /api/chat/stream` using server-sent events |

See [API](../../docs/api.md) for the route list and
[`docs/openapi.snapshot.json`](../../docs/openapi.snapshot.json) for the checked-in contract.

## Configuration

Copy the minimum example or the complete reference from the repository root:

```bash
cp .env.example .env
# or
cp .env.full.example .env
```

The main setting groups are:

| Group | Important settings |
| --- | --- |
| Runtime | `LOGAN_ENV`, `LOGAN_SECRET_KEY`, `LOGAN_LOG_LEVEL` |
| Persistence | `LOGAN_DATABASE_PATH`, `LOGAN_LOCAL_OBJECT_STORE_DIR`, `LOGAN_MAX_UPLOAD_BYTES` |
| Browser access | `LOGAN_WEB_BASE_URL`, `LOGAN_CORS_ALLOWED_ORIGINS` |
| Authentication | `LOGAN_SSO_AUTHORIZE_URL`, `LOGAN_SSO_TOKEN_URL`, `LOGAN_SSO_CLIENT_ID` |
| Analysis | `LOGAN_LLM_PROVIDER` |
| AI Platform | model, host, token or iB2B credentials, TLS, proxy, timeout, and token settings |

`app/config.py` is the runtime contract and `.env.full.example` documents every supported setting.
Production validation requires a strong secret, complete SSO, and TLS verification.

## Run locally

From the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
python -m alembic -c apps/api/alembic.ini upgrade head
python -m uvicorn app.main:app --reload --env-file .env --app-dir apps/api --host 127.0.0.1 --port 8000
```

On Windows, `scripts\local.bat -ApiOnly` performs dependency setup and migrations before starting
the API. Run the complete local stack with `scripts\local.bat`.

OpenAPI UI is available at `http://localhost:8000/docs`.

## Database migrations

Apply and verify migrations:

```bash
python -m alembic -c apps/api/alembic.ini upgrade head
python -m alembic -c apps/api/alembic.ini check
```

For a model change, generate and review a revision:

```bash
python -m alembic -c apps/api/alembic.ini revision --autogenerate -m "describe change"
```

Every committed revision must implement both `upgrade()` and `downgrade()`.

## Validation

```bash
python -m ruff check apps tests scripts
python -m pytest -q
python -m pytest tests/api/test_api.py -q
python -m pytest tests/api/test_sso_auth_service.py -q
python -m pytest tests/api/test_openapi_contract.py -q
python scripts/export_openapi.py --out docs/openapi.snapshot.json
```

Tests are deterministic and offline. External-service behavior uses an injected gateway or HTTP
transport.

## Common changes

### Add or change an API endpoint

Add the handler in `app/api`, define request and response models in `app/schemas`, enforce
authentication and ownership, update API tests, then regenerate the OpenAPI snapshot. Update
`apps/web/src/lib/api.ts` when the browser consumes the change.

### Change database state

Update `app/models/tables.py` and `app/sqlalchemy_store.py`, add an Alembic revision, and verify
both migration commands. Keep the five-table model and result-JSON contract explicit when
considering new persistence.

### Change the analysis pipeline

Keep `logan_analysis` independent of FastAPI and SQLAlchemy. Update the pipeline tests, progress
consumer in `apps/web/src/components/AnalysisProgressPanel.tsx`, report consumers, and
[Analysis pipeline](../../docs/analysis-pipeline.md).

### Change configuration

Update `app/config.py`, `.env.example` when the setting is part of minimum setup,
`.env.full.example`, `docker-compose.yml`, tests, and the relevant documentation in the same
change.

## Safety rules

- Redact content before templates, model calls, and report display.
- Do not persist raw prompts, credentials, tokens, unrestricted paths, or model diagnostics.
- Keep progress metadata count-based and sanitize stored failures.
- Keep production authentication SSO-only and preserve case ownership checks.
- Keep TLS verification enabled in production.
- Never commit `.env`, `.logan/`, credentials, SSO responses, model responses containing customer
  data, or raw customer logs.

## Reading order

1. `app/main.py`
2. `app/config.py`
3. `app/dependencies.py`
4. `app/api/auth.py` and `app/services/sso_auth_service.py`
5. `app/api/cases.py`
6. `app/sqlalchemy_store.py`
7. `logan_analysis/pipeline.py` and `logan_analysis/models.py`
8. `app/api/reports.py`
9. `app/api/chat.py`
10. `tests/api/test_api.py`
