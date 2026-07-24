# LogAn API (`apps/api`)

`apps/api` is the FastAPI **control plane** of the LogAn monorepo — the case-based incident log-diagnosis platform whose two sibling apps are the analysis pipeline + Temporal worker (`apps/workers`) and the Next.js workbench (`apps/web`). It owns everything stateful and security-sensitive: SSO-only authentication and cookie sessions, per-case RBAC and organization isolation, CRUD for cases/collaborators/uploads (local disk or S3/MinIO, incl. multipart), starting analysis runs and choosing the orchestrator, and the read APIs + SSE streams that back the five workbench views (Data Summary, Temporal, Tabular Logs, Causal Graph, Causal Summary). It **orchestrates but does not implement** the analysis math — that lives in `apps/workers` and is invoked in-process (`local`) or over Temporal. All metadata flows through one `MetadataStore` contract implemented by `SQLAlchemyStore`; disposable tests use the same implementation over an isolated in-memory SQLite database. Start from the root [`README.md`](../../README.md) (quick start + env vars) and [`CONTRIBUTING.md`](../../CONTRIBUTING.md) (conventions); [`CLAUDE.md`](../../CLAUDE.md) is the architecture crib.

## Tech stack

- **Python ≥3.11**, **FastAPI / Starlette**, **Pydantic v2**, **uvicorn** (ASGI)
- **SQLAlchemy 2.x** over SQLite and PostgreSQL (psycopg3)
- **bcrypt** (legacy password hashing) + **cryptography Fernet** (credential encryption)
- **httpx** (async: AI Platform, SSO, analytics sinks/queries), **boto3** (S3/MinIO)
- **temporalio** (durable orchestrator client)
- **prometheus-client**, **opentelemetry** (api/sdk/otlp, optional)
- **pytest** with httpx `AsyncClient` / `ASGITransport`; **ruff** (lint, line length 100)

Distribution is `logan-platform` (root `pyproject.toml`, setuptools). The import package for this app is top-level **`app`** (`from app.main import create_app`); workers import as `logan_workers`. Tests get both on `sys.path` via `pythonpath = ["apps/api", "apps/workers"]`; uvicorn uses `--app-dir apps/api`.

## Directory layout

```
apps/api/
├── app/
│   ├── main.py               # create_app factory: app.state wiring, 6 routers, middleware, model-gateway default
│   ├── config.py             # frozen Settings from LOGAN_* env; validate_for_runtime(); settings singleton
│   ├── dependencies.py       # DI seams: get_store, get_model_gateway, current_user, require_admin, require_case_permission
│   ├── store.py              # MetadataStore Protocol, record dataclasses, sanitize_* helpers, store factories
│   ├── sqlalchemy_store.py   # SQLAlchemyStore (SQLite/Postgres): AnalysisResult fan-out, get_report_* SQL views, analytics sinks/queries
│   ├── db.py                 # SQLAlchemy DeclarativeBase (Base) — 7 lines
│   ├── observability.py      # API logging/otel/http/model/sink metrics and label sanitizers
│   ├── rate_limit.py         # RateLimitMiddleware: per-session/IP fixed-window over /api (off by default)
│   ├── api/                  # route handlers (six APIRouters)
│   │   ├── auth.py           # SSO login/callback/session, mock SSO, /me, /logout; /register & /login → 410
│   │   ├── capabilities.py   # GET /api/capabilities (models/views/upload limits for the UI)
│   │   ├── cases.py          # cases, collaborators, uploads, analysis runs, progress
│   │   ├── reports.py        # five report views, exports, feedback
│   │   ├── chat.py           # POST /api/chat + /api/chat/stream (SSE); /api/tasks/execute stub
│   │   ├── admin.py          # users, policy groups, audit-log export, retention
│   │   └── scim.py           # SCIM 2.0 user/group provisioning (raw dicts, not schemas)
│   ├── schemas/              # Pydantic request/response models: auth.py, case.py, chat.py, admin.py
│   ├── services/
│   │   ├── model_gateway.py            # gateway errors + helpers (the contract)
│   │   ├── model_gateway_factory.py    # shared API/worker gateway construction
│   │   ├── aiplatform_model_gateway.py # production LLM client implementing responses(...)
│   │   ├── object_store.py             # local file:// + s3:// (MinIO): presigned single + multipart, sha256
│   │   ├── analysis_inputs.py          # materialize S3 → tmp for the local pipeline
│   │   ├── analysis_artifacts.py       # per-step JSON manifests
│   │   ├── analytics_sinks.py          # mirror results to ClickHouse/OpenSearch
│   │   ├── analytics_queries.py        # serve views from external analytics
│   │   └── sso_auth_service.py         # OIDC authorize-URL, token exchange, provision_user
│   ├── models/tables.py      # SQLAlchemy 2 ORM tables (orgs, users, sessions, cases, analysis_runs, job_events, logs, causal_*, audit_logs, …)
│   └── core/security.py      # bcrypt_sha256, session token issue/hash, Fernet credential encryption + key-id keyring
└── migrations/               # Postgres-only incremental .sql (0001_initial, 0002_analysis_step_artifacts, 0003_enterprise_policy_scim)
```

## How it fits

**To `apps/workers` (in-process import of `logan_workers`).** For the `local` orchestrator the API embeds the pipeline: `SQLAlchemyStore.run_analysis` calls `AnalyzeCasePipeline().run(...)` from `logan_workers.pipeline` with a `progress_callback` that records job events. It also imports `logan_workers.activities.export.export_analysis` (view/export rendering), `logan_workers.models` (`AnalysisResult`, `ExportArtifact`, `EvidenceRef`, `OFFENDING_SIGNALS`), and `logan_workers.activities.inference.MockAIPlatformAnnotationGateway` (deterministic mock provider). For the `temporal` orchestrator it calls `logan_workers.temporal_client.start_analyze_case_workflow` (+ `TemporalClientConfig`) to dispatch to the worker, then returns without an in-process result (the run stays `processing` until the worker reports back via job events).

**Model gateway contract.** Any object with an async `responses(user_id, model, instructions, input, stream, metadata, reasoning_effort, ...)` method works. It is injected via `create_app(model_gateway=...)`, held on `app.state.model_gateway`, passed as `gateway=` into the pipeline, and used directly by `chat/stream`.

**Object-store seam.** `create_app(s3_client_factory=...)` injects a fake S3 client (stored on `app.state.s3_client_factory`, threaded through every `object_store` call).

**Pipeline metrics.** Pipeline step names and counters live in
`logan_workers.observability`; API metrics share the same Prometheus registry.

**To `apps/web` (Next.js).** REST + `text/event-stream` over HTTP with the httpOnly `logan_session` cookie; CORS `allow_credentials` with origins from `LOGAN_CORS_ALLOWED_ORIGINS`; the SSO callback 302-redirects to `LOGAN_WEB_BASE_URL`; `GET /api/capabilities` advertises models/views/upload limits. The generated [`docs/openapi.snapshot.json`](../../docs/openapi.snapshot.json) is the frozen contract asserted by a contract test. See [`docs/architecture.md`](../../docs/architecture.md), [`docs/data-model.md`](../../docs/data-model.md), and [`docs/life-of-a-log-line.md`](../../docs/life-of-a-log-line.md).

## Run it locally

The API reads **process env only** — it never parses `.env`. Load it first, then start the server:

```bash
set -a; source .env; set +a                        # bash; on Windows run scripts\local.ps1 instead
uvicorn app.main:app --reload --app-dir apps/api    # or: make api  (binds 0.0.0.0:8000)
```

`scripts\local.ps1` bootstraps, loads `.env`, and starts both API and web. Persistence and local sign-in are env-driven:

| Goal | Settings |
| --- | --- |
| Default (SQLite `sqlite:///.logan/logan.db`) | `LOGAN_STORE_BACKEND=auto` |
| Throwaway SQLite store (compatibility alias) | `LOGAN_STORE_BACKEND=memory` |
| PostgreSQL | `LOGAN_DATABASE_URL=…` + `LOGAN_STORE_BACKEND=sqlalchemy` |
| Sign in without a real IdP | `LOGAN_SSO_ENABLED=true` + `LOGAN_SSO_MOCK_ENABLED=true` |

Web workbench (separate app): `npm run dev --workspace @logan/web` (or `make web`). Full stack via containers: `make quickstart-up` (`docker-compose.quickstart.yml`) or `make full-stack-up` (postgres/redis/minio/clickhouse/opensearch/temporal/api/worker). `apps/api/app/config.py` is the authoritative list of every `LOGAN_*` setting; `.env.example` / `.env.full.example` are the annotated references.

## Test, lint, typecheck

```bash
python -m pytest -q                                       # full backend suite, no services, ~2 min
python -m pytest tests/api/test_api.py -q                 # API behavior on isolated SQLite
python -m pytest tests/api/test_sqlalchemy_persistence.py -q  # persistence behavior on SQLAlchemy
python -m pytest tests/api/test_openapi_contract.py -q    # OpenAPI contract (see below)
ruff check apps tests scripts                             # lint, line length 100
make lint                                                 # ruff + compileall apps/api apps/workers + web tsc
```

After **any** route or schema change, regenerate the contract snapshot with `make openapi-snapshot` (writes `docs/openapi.snapshot.json`) or `test_openapi_contract.py` fails. Other targeted suites: `test_security.py`, `test_object_store.py`, `test_sso_auth_service.py`, `test_aiplatform_model_gateway.py`, `test_analytics_sinks.py`, `test_analytics_queries.py`, `test_deployment_manifests.py`, `test_migration_cli.py`. There is no separate typecheck for this app — `make lint`'s `compileall` is the Python gate (web `tsc` belongs to `apps/web`). The `integration` and `staging` markers are opt-in (need real services) and excluded from the default run.

## Key concepts

- **Case** — the unit of work (`id` + human `case_key` `LOGAN-YYYYMMDD-NNNN`); status lifecycle `created → uploading → processing → ready/failed/cancelled`.
- **Analysis run** — one execution over a case's inputs, with `run_number`, `status`, `progress`, and (when `local`) an embedded `AnalysisResult`.
- **Five views** — `data_summary`, `temporal`, `logs` (tabular), `causal_graph`, `causal_summary`; the fixed set the UI renders and the API serves per run.
- **Golden signal + `OFFENDING_SIGNALS`** — per-template classification; the `attention` scope surfaces only offending signals.
- **Template / representative sample / annotation** — drain-style log templating, sampled exemplars, and LLM annotations (`golden_signal`, `fault_categories`, `entities`, `severity`, `confidence`, `rationale`).
- **Job event** — append-only, idempotency-keyed step record (`started/completed/failed/cancelled`) that drives `run.progress` and step artifacts.
- **Step artifact / manifest** — per-completed-step JSON written to the object store; sanitized, count-only.
- **One store implementation** — production and tests both use `SQLAlchemyStore`; `create_ephemeral_store` selects isolated in-memory SQLite for tests.
- **Orchestrator** — `LOGAN_ANALYSIS_ORCHESTRATOR` = `local` (in-process) or `temporal` (dispatch to worker).
- **Org isolation + RBAC** — global roles `admin`/`engineer`; per-case collaborator roles `owner`/`editor`/`viewer`; policy groups grant case access to groups; everything scoped to `organization_id`.
- **SSO-only auth** — OIDC authorization-code flow; mock SSO for local/e2e; password endpoints are `410 Gone`.
- **Retention** — age-based scrubbing of raw log text, audit logs, exports, and step artifacts. See [`docs/glossary.md`](../../docs/glossary.md) and [`docs/reliability-and-explainability.md`](../../docs/reliability-and-explainability.md).

## Where to start reading

1. `apps/api/app/main.py` — composition root: what gets wired and in what order.
2. `apps/api/app/config.py` — the `Settings` surface, i.e. the entire configuration contract.
3. `apps/api/app/dependencies.py` — the auth + RBAC seams every route depends on.
4. `apps/api/app/store.py` — `MetadataStore` Protocol, record types, redaction helpers, and store factories.
5. `apps/api/app/api/cases.py` + `reports.py` — the write lifecycle and read/report surfaces.
6. `apps/api/app/api/auth.py` + `apps/api/app/services/sso_auth_service.py` — SSO login/callback/session flow.
7. `apps/api/app/api/chat.py` — SSE streaming + model-gateway usage pattern.
8. `apps/api/app/services/model_gateway.py` then `aiplatform_model_gateway.py` — the gateway contract + production impl.
9. `apps/api/app/sqlalchemy_store.py` — skim `__init__`/`_session`, `run_analysis`, `_fan_out_analysis_result`, and `get_report_*`.
10. `apps/api/app/models/tables.py` + `apps/api/app/observability.py` — relational schema + API metrics.
11. `tests/api/test_api.py` — how `create_app` + fakes + cookie auth are wired for tests.

## Common tasks

- **Add a REST endpoint** — add the handler to the right router in `apps/api/app/api/*.py` (or a new router registered in `main.py`); declare request/response models in `apps/api/app/schemas/*.py`; depend on `current_user` + `get_store` and gate case-scoped routes with `require_case_permission`; then run `make openapi-snapshot` and the contract test.
- **Add a `MetadataStore` capability** — add the signature to the `MetadataStore` Protocol in `store.py`, implement it once on `SQLAlchemyStore` (add ORM columns in `models/tables.py` + a Postgres migration in `migrations/` if schema changes), and cover API behavior plus persistence in `tests/api/test_api.py` and `tests/api/test_sqlalchemy_persistence.py`.
- **Add a view / read endpoint served by SQL** — add the route in `reports.py`, implement `get_report_<name>` on `SQLAlchemyStore` over the normalized tables (and optionally external analytics), and cover the response contract.
- **Add or change a config setting** — add the env-read field to `Settings` in `config.py` (add a `validate_for_runtime` check if production-sensitive), then propagate to `.env.full.example`, the README env section, `docker-compose.yml`, and the k8s/EKS configmaps — `tests/api/test_deployment_manifests.py` enforces sync.
- **Wire fakes in a test** — `create_app(store=create_ephemeral_store(Settings(...)), model_gateway=MockAIPlatformAnnotationGateway(), s3_client_factory=lambda _: FakeS3Client())`; drive it with httpx `AsyncClient` over `ASGITransport`; authenticate via `store.register_user` + `store.create_session` and set the `logan_session` cookie (see `_authenticated_client` in `tests/api/test_api.py`).
- **Switch the orchestrator** — `LOGAN_ANALYSIS_ORCHESTRATOR=local` runs the in-process pipeline (returns an `AnalysisResult`); `=temporal` dispatches `start_analyze_case_workflow` and leaves the run `processing` until the worker reports back — temporal also needs `LOGAN_TEMPORAL_*` and a running worker.

## Conventions & gotchas

- **One persistence path.** Store behavior is implemented once in `sqlalchemy_store.py`; `store.py` owns the contract, records, shared helpers, and factories. `InMemoryStore` remains only as a deprecated constructor compatibility shim.
- **Process env only.** `Settings` is a frozen dataclass evaluated at import time — the app never loads `.env`. Tests construct a fresh `Settings(...)` and pass it into `create_store`/`create_ephemeral_store` rather than mutating env.
- **Redaction is a hard rule.** Raw log text, prompts, credentials, tokens, DB URLs, and full paths must never reach `job_events` metadata, step manifests, metric labels, or audit metadata. Enforced by `sanitize_error_message` / `sanitize_job_metadata` / `sanitize_artifact_metadata` / `sanitize_workflow_payload` (`store.py`), admin `_safe_audit_metadata`, and the `observability` label sanitizers. Model calls receive only redacted representative samples. See [`docs/security.md`](../../docs/security.md).
- **Report queries.** `reports.py` delegates report reads to `SQLAlchemyStore`, which answers from normalized SQL or external analytics when `LOGAN_EXTERNAL_ANALYTICS_QUERIES_ENABLED`.
- **RBAC `hide_forbidden`.** Read endpoints pass `hide_forbidden=True` (permission denied → `404`, so existence isn't leaked); write/owner endpoints use `False` (→ `403`).
- **Auth is SSO-only.** `POST /api/auth/register` and `/login` return `410`. The session cookie is `logan_session` (sha256-hashed token stored, 365-day expiry, `Secure` only when `LOGAN_ENV=production`, `SameSite=lax`).
- **Singletons, not per-request DI.** `get_model_gateway` and the `s3_client_factory` just read process-wide objects off `app.state` — they are not per-request dependencies.
- **`PIPELINE_STEP_NAMES` sync.** Adding a pipeline step requires updating `logan_workers.observability.PIPELINE_STEP_NAMES` **and** `scripts/full_stack_smoke.py` `PIPELINE_STEPS`, then re-running the benchmark.
- **Migrations.** `SQLAlchemyStore` auto-creates schema via `create_all` and, on **Postgres only**, runs checksummed incremental SQL from `apps/api/migrations` under an advisory lock — changing an already-applied migration's bytes is a hard error. SQLite has no incremental migrations.
- **`create_app(**_legacy_options)` silently ignores unknown kwargs** — a compatibility shim, not a feature.
- **Background analysis** (`?background=true`) runs as an asyncio task tracked on `app.state.analysis_tasks`; deleting or cancelling the case/run cancels the task.

See [`CONTRIBUTING.md`](../../CONTRIBUTING.md) for repo-wide conventions and [`docs/operations.md`](../../docs/operations.md) for deploy/runbook detail.
