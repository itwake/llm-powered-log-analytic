# CLAUDE.md

LogAn: case-based incident log diagnosis. Users create a case, upload logs, run an analysis,
and review five views (Summary, Temporal, Logs, Causal Graph, Causal Summary). Monorepo:
FastAPI API (`apps/api`), Python analysis pipeline + Temporal worker (`apps/workers`),
Next.js workbench (`apps/web`).

## Commands

```bash
python -m pytest -q                          # full backend suite (~2 min, no services needed)
python -m pytest tests/api/test_api.py -q    # single file
ruff check apps tests scripts                # lint (line length 100)
npm run lint --workspace @logan/web          # web typecheck (tsc --noEmit)
npm run e2e                                  # Playwright; self-contained, starts both servers
make openapi-snapshot                        # regenerate docs/openapi.snapshot.json after API changes
python -m logan_workers.evaluation.run --benchmark benchmarks/logan/checkout_incident \
  --out .logan/evaluation/report.json        # deterministic benchmark; non-zero exit = blocker
scripts\dev.ps1                              # Windows: bootstrap + run API and web (loads .env)
python scripts/seed_demo_case.py             # seed a demo case against a running API
```

Local run: API `uvicorn app.main:app --reload --app-dir apps/api` + web
`npm run dev --workspace @logan/web`. The API reads process env only — it does **not** parse
`.env`; load it first (`scripts\dev.ps1` does, or `set -a; source .env; set +a`).

## Architecture crib

- Pipeline (`apps/workers/logan_workers/pipeline.py`), 10 steps in order: ingest_paths,
  merge_entries, preprocess_redact, drain_templating, representative_sampling,
  ai_platform_annotation, broadcast_annotations, temporal_aggregation, causal_graph,
  causal_summary, then export_artifacts. Each emits started/completed/failed events with
  count-only metadata.
- Two `MetadataStore` implementations that must stay behavior-identical: `apps/api/app/store.py`
  (in-memory, tests) and `apps/api/app/sqlalchemy_store.py` (SQLite/PostgreSQL). Changes land in
  both, tested in `tests/api/test_api.py` and `tests/api/test_sqlalchemy_persistence.py`.
- Tests inject fakes via `create_app(store, model_gateway=..., s3_client_factory=...)`; no
  network in unit tests. `LOGAN_LLM_PROVIDER=mock` is the deterministic local provider;
  `ai_platform` is production-only.
- Auth is SSO-only (password endpoints return 410). Local sign-in = mock SSO, enabled via env
  in `.env.example`, both compose files, and `playwright.config.ts`.

## Hard rules

- Raw log text, prompts, credentials, tokens, DB URLs, and full file paths never go into
  job_events metadata, step manifests, metric labels, audit metadata, or benchmark reports.
  Model calls get redacted representative samples only.
- New `LOGAN_*` setting → update `config.py`, `.env.full.example`, README env section,
  `docker-compose.yml`, and the k8s/EKS configmaps (manifest tests assert sync).
- New pipeline step → also update `PIPELINE_STEP_NAMES` (`apps/api/app/observability.py`) and
  `PIPELINE_STEPS` (`scripts/full_stack_smoke.py`), and re-run the benchmark.
- API route/schema changes → regenerate `docs/openapi.snapshot.json` or the contract test fails.
- `.env*.example` stay LF, `*.bat` stay CRLF (`.gitattributes`); no unquoted spaced env values.
- CI installs with `-c constraints.txt`; refresh it deliberately (see CONTRIBUTING.md), never ad hoc.

See CONTRIBUTING.md for the full conventions and docs/glossary.md for domain terms.
