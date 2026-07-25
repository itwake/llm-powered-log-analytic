# LogAn API

The FastAPI application owns authentication, case access, uploads, analysis execution,
persistence, reports, feedback, chat, admin APIs, and Prometheus metrics.

## Runtime

`app.main:create_app` creates one SQLAlchemy-backed store and one model gateway. Upload bytes and
step manifests are written below `LOGAN_LOCAL_OBJECT_STORE_DIR`. Starting an analysis calls
`logan_analysis.pipeline.AnalyzeCasePipeline` in process, records progress events, and writes the
normalized result through the same store.

SQLite is the default database. A PostgreSQL SQLAlchemy URL uses the same implementation and
migrations; it is not a separate store backend.

## Development

```bash
python -m pip install -e ".[dev]"
uvicorn app.main:app --reload --app-dir apps/api --port 8000
```

Useful commands:

```bash
python scripts/run_migrations.py
python scripts/export_openapi.py --out docs/openapi.snapshot.json
python -m pytest tests/api tests/analysis
```

Tests use `create_ephemeral_store`, which is the production SQLAlchemy store over an isolated
in-memory SQLite database. Model behavior is injected through `create_app(model_gateway=...)`.

## Analysis package

`logan_analysis` is internal to the API application but remains independent from HTTP,
authentication, and persistence code. The dependency direction is `app -> logan_analysis`; the
analysis package must not import `app`.

Run its deterministic benchmark with:

```bash
python -m logan_analysis.evaluation.run \
  --benchmark benchmarks/logan/checkout_incident \
  --out .logan/evaluation/report.json \
  --markdown .logan/evaluation/report.md
```

## Important modules

- `app/api/cases.py` — cases, collaborators, local uploads, and analysis starts
- `app/api/reports.py` — SQL-backed reports, exports, artifacts, and feedback
- `app/sqlalchemy_store.py` — the single persistence implementation
- `app/services/object_store.py` — local file URI/path and digest helpers
- `app/services/analysis_artifacts.py` — safe local step manifests
- `app/services/model_gateway_factory.py` — configured real or mock model gateway
- `app/observability.py` — HTTP/model Prometheus metrics
- `app/config.py` — authoritative runtime settings
- `logan_analysis/pipeline.py` — in-process analysis orchestration
- `logan_analysis/activities/` and `logan_analysis/algorithms/` — analysis steps and algorithms
- `logan_analysis/evaluation/` — deterministic benchmark and scale tooling

The API never returns storage filesystem paths in the upload-start response. Clients receive a
single authenticated content URL; that request validates the size, computes SHA-256, and completes
the upload.
