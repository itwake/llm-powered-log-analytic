# AGENTS.md

LogAn is a focused incident log analysis application. Users create a case, upload logs, run an
analysis, and review the resulting logs, temporal activity, causal candidates, and summary.

The repository contains two deployable applications:

- `apps/api`: FastAPI routes, SQLAlchemy persistence, local file storage, and the analysis package.
- `apps/web`: the Next.js user interface.

Read `CONTRIBUTING.md` and the relevant file under `docs/` before changing a subsystem. Keep code,
tests, configuration examples, and documentation consistent in the same change.

## Commands

```bash
python -m pytest -q
python -m pytest tests/api/test_api.py -q
python -m ruff check apps tests scripts
npm run lint
npm run typecheck
npm run build
python scripts/export_openapi.py --out docs/openapi.snapshot.json
python -m alembic -c apps/api/alembic.ini upgrade head
python -m alembic -c apps/api/alembic.ini check
```

On Windows, `scripts\local.bat` bootstraps dependencies, applies migrations, and starts the API
and web application. It also accepts `-ApiOnly`, `-WebOnly`, and `-SkipInstall`.

For manual local development, start the applications in separate terminals:

```bash
python -m uvicorn app.main:app --reload --env-file .env --app-dir apps/api --host 127.0.0.1 --port 8000
npm run dev --workspace @logan/web
```

## Architecture

- `apps/api/app` owns HTTP routes, authentication, configuration, persistence, and external
  service adapters.
- `apps/api/logan_analysis` owns the analysis domain models, algorithms, activities, prompts, and
  ordered pipeline. Keep this package independent of FastAPI and database details.
- `apps/web/src` owns the browser application. API calls belong in `src/lib/api`; reusable UI
  belongs in `src/components`.
- Analysis runs execute as asynchronous tasks in the API process. Shutdown cancels active tasks.
- `SQLAlchemyStore` is the single metadata store. Production and local development use SQLite;
  tests use the same implementation with an in-memory database.
- Uploads are stored below `LOGAN_LOCAL_OBJECT_STORE_DIR`. Analysis accepts completed upload
  identifiers and resolves their generated local object paths through the store.
- A completed run persists one validated `AnalysisResult`. Report endpoints and chat read that
  result instead of maintaining another analytical schema.

The pipeline steps in `apps/api/logan_analysis/pipeline.py` run in this order:

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

`LOGAN_LLM_PROVIDER` is either `none` or `ai_platform`. The `none` mode runs the deterministic
pipeline without model calls. The `ai_platform` mode adds template annotation, generated summary
text, and case chat. Tests may inject a fake `ModelGateway`, but fake gateways are not runtime
providers.

## Change contracts

- API route or schema change: update its tests and regenerate `docs/openapi.snapshot.json`.
- Database model change: add an Alembic revision and verify both `upgrade head` and `check`.
- Pipeline model or step change: update pipeline tests, progress/report consumers, and
  `docs/analysis-pipeline.md`.
- Configuration change: update `apps/api/app/config.py`, `.env.example` when required for the
  minimum setup, `.env.full.example`, `docker-compose.yml`, and the relevant documentation.
- Web dependency change: update `apps/web/package.json` and the root `package-lock.json`.
- User-visible workflow change: update `README.md`, `docs/getting-started.md`, or
  `docs/user-guide.md` as appropriate.

## Safety and quality rules

- Raw customer logs, prompts, credentials, tokens, database URLs, and unrestricted filesystem
  paths must not appear in progress metadata, stored error messages, logs, or model diagnostics.
- Redact log content before template generation, model input, and report display. Model calls may
  receive only bounded, redacted representative samples and evidence packets.
- Keep production authentication SSO-only. Development may use the local default user only when
  `LOGAN_SSO_AUTHORIZE_URL` is empty. Browser sessions use HTTP-only cookies, and every
  case-related route must enforce ownership.
- Do not weaken TLS verification in production or commit `.env`, `.logan/`, credentials, SSO
  responses, access tokens, model responses containing customer data, or raw customer logs.
- Keep unit tests deterministic and offline. Use synthetic fixtures and injected gateways for
  external-service behavior.
- Preserve evidence identifiers and source references through analysis transformations. Causal
  edges are investigation candidates, not proof, and must remain labeled accordingly.
- Run the smallest relevant test while iterating, then run the full Python and web checks before
  handing off a completed change.
