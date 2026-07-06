# Contributing to LogAn

This guide covers the conventions you need before changing code. For getting the app running,
see the README Quick Start; for domain vocabulary, see [docs/glossary.md](docs/glossary.md).

## Repository Map

| Path | What lives there |
| --- | --- |
| `apps/api/app/api/` | FastAPI routers: auth, cases, chat, admin, SCIM, capabilities |
| `apps/api/app/schemas/` | Pydantic request/response models |
| `apps/api/app/store.py` | In-memory `MetadataStore` (tests and local experiments) |
| `apps/api/app/sqlalchemy_store.py` | Durable SQLAlchemy `MetadataStore` (SQLite/PostgreSQL) |
| `apps/api/app/services/` | Model gateway, object store, analytics sinks/queries, SSO |
| `apps/api/app/config.py` | Every `LOGAN_*` setting with its default |
| `apps/api/app/observability.py` | Logging, Prometheus metrics, OTel, safe-label rules |
| `apps/api/migrations/` | Incremental SQL DDL applied by `scripts/run_migrations.py` |
| `apps/workers/logan_workers/pipeline.py` | The 10-step analysis pipeline orchestrator |
| `apps/workers/logan_workers/activities/` | One module per pipeline step |
| `apps/workers/logan_workers/algorithms/` | Drain adapter, redactors, parsers, causal scoring |
| `apps/workers/logan_workers/evaluation/` | Offline benchmark evaluator and CLI |
| `apps/web/src/` | Next.js workbench (App Router, MUI, ECharts, Cytoscape.js) |
| `tests/` | `api/`, `workers/`, `integration/`, `e2e/` (Playwright) |
| `benchmarks/logan/checkout_incident/` | Deterministic labeled benchmark |
| `infra/` | Dockerfiles, Kubernetes and EKS manifests |
| `scripts/` | Dev launcher, demo seeding, migrations, smoke, OpenAPI export |

## Quality Gates

Run before every PR:

```bash
python -m pytest -q
ruff check apps tests scripts
npm run lint --workspace @logan/web
```

Situational:

- Changed parsing, templating, annotation, causal ranking, or summaries? Run the benchmark and
  treat a non-zero exit as a blocker:
  `python -m logan_workers.evaluation.run --benchmark benchmarks/logan/checkout_incident --out .logan/evaluation/report.json`
- Changed any API route or schema? Regenerate the contract snapshot:
  `python scripts/export_openapi.py --out docs/openapi.snapshot.json` (`make openapi-snapshot`).
- Touched the web UI flows? `npm run e2e` (self-contained; starts both servers with mock SSO).
- Touched compose/k8s/Dockerfiles? `python -m pytest tests/api/test_deployment_manifests.py`.

## Conventions That Will Bite You

### Two stores, one behavior

`store.py` (in-memory) and `sqlalchemy_store.py` (durable) implement the same `MetadataStore`
surface and **must stay behavior-identical**. There is no shared abstract base enforcing this —
parity is maintained by hand. Any new store method or behavior change lands in **both** files,
with coverage in `tests/api/test_api.py` (in-memory via `create_app`) and
`tests/api/test_sqlalchemy_persistence.py` (durable).

### Adding a `LOGAN_*` setting touches five places

1. `apps/api/app/config.py` — the `Settings` field and default.
2. `.env.full.example` — documented entry in the right section (`.env.example` too if the
   minimal local run needs it).
3. README "Environment Variables" — one bullet if operators should know about it.
4. `docker-compose.yml` `x-logan-env` (and `docker-compose.quickstart.yml` if the quickstart
   needs it).
5. `infra/k8s/configmap.yaml` / `infra/eks/logan-configmap.yaml` for deployed values.

`tests/api/test_deployment_manifests.py` asserts several of these stay in sync.

### Redaction red lines

Raw log text, prompts, model inputs, credentials, tokens, cookies, database URLs, S3 secrets,
and full file paths must never appear in: `job_events` metadata (count-only), `step_manifest`
artifacts, Prometheus label values, audit log metadata, benchmark reports, or error messages
returned to clients. Model calls receive **redacted representative samples only** — never full
raw lines. Tests assert these properties; keep them passing rather than loosening them.

### Tests never touch the network

Unit tests build the app with explicit fakes: `create_app(InMemoryStore(settings),
model_gateway=MockAIPlatformAnnotationGateway(), s3_client_factory=...)`. New external
integrations must follow the same seam pattern: a real adapter, a deterministic fake, and an
injection point on `app.state`.

### Authentication is SSO-only

Password register/login endpoints return 410. Local sign-in uses the built-in mock SSO
(`LOGAN_SSO_ENABLED=true` + `LOGAN_SSO_MOCK_ENABLED=true`, wired in `.env.example`,
`docker-compose*.yml`, and `playwright.config.ts`). Production must keep the mock disabled.

### Pipeline steps are a closed, observable set

Each step in `pipeline.py` emits `started`/`completed`/`failed` events with count-only metadata.
When adding a step, also update `PIPELINE_STEP_NAMES` in `apps/api/app/observability.py` and
`PIPELINE_STEPS` in `scripts/full_stack_smoke.py`, then re-run the benchmark.

### Windows friendliness

`.env*.example` are pinned to LF and `*.bat` to CRLF in `.gitattributes` — keep it that way, and
avoid unquoted spaced values in env templates. Local artifact paths stay short
(`.logan/object-store/step-artifacts/{hash}.json`) for Windows path limits.

## Dependencies

`pyproject.toml` uses floor pins (`>=`) so installs drift over time. CI and the Docker images
install with `-c constraints.txt` for reproducibility. After a deliberate upgrade, refresh it
from a clean venv:

```bash
python -m pip install -e . pytest pytest-asyncio ruff
python -m pip freeze --exclude-editable > constraints.txt
```

Then run the full quality gates before committing the new constraints. The npm side is pinned by
`package-lock.json` (`npm ci` in CI).

## Common Tasks

**Add an API endpoint**: router handler in `apps/api/app/api/` → request/response models in
`apps/api/app/schemas/` → store methods in **both** stores → tests in `tests/api/test_api.py`
and `tests/api/test_sqlalchemy_persistence.py` → regenerate the OpenAPI snapshot.

**Add a pipeline step**: new module in `apps/workers/logan_workers/activities/` → wire a
`run_step` call in `pipeline.py` with count-only metadata → update the two step-name sets above
→ tests in `tests/workers/test_pipeline.py` → run the benchmark.

**Change a report view**: SQL fan-out read in `sqlalchemy_store.py` + the same shape from
`store.py` → API route in `cases.py` → web page under
`apps/web/src/app/(app)/cases/[caseId]/runs/[runId]/` → e2e assertion if the flow changed.
