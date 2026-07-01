# LogAn Platform

LogAn is a case-based incident log diagnosis platform for Support, SRE, and development teams. Users create an incident case, upload related logs, run an analysis, and review five linked views: Data Summary, Temporal View, Tabular Logs, Causal Graph, and Causal Summary.

This repository is the staged foundation for the final product. The current implementation includes a runnable FastAPI backend, durable SQLAlchemy metadata store with normalized PostgreSQL/SQLite analysis fan-out, step-level analysis manifest artifacts in local object storage or S3/MinIO, RBAC case access with per-case collaborators, admin user/audit/settings/retention APIs, optional API rate limiting, Prometheus `/metrics`, optional OpenTelemetry FastAPI tracing, optional ClickHouse/OpenSearch analytics sink publishing with managed lifecycle and durable write records, opt-in temporal/log report reads over external analytics stores, an in-memory test option, local object-byte uploads, optional S3/MinIO single and multipart raw uploads with completed-upload analysis materialization, synchronous local analysis, a Temporal workflow/worker activity path for durable SQLAlchemy-backed analysis, candidate causal evidence with temporal precedence, lift, PGEM-style transition scoring, and Granger-style lagged-linear scoring, evidence-first LLM-backed causal summaries with cautious evidence-based fallback, synthetic checkout incident fixtures, tests, an authenticated AI Platform-backed chat stream, a Next.js workbench shell with ECharts Temporal View and Cytoscape Causal Graph visualizations, a minimal admin view, and deployment scaffolding.

## Architecture

- `apps/api`: FastAPI API, Pydantic v2 schemas, auth/session handling, AI Platform chat gateway support, SQLAlchemy metadata persistence with normalized analysis rows, optional ClickHouse/OpenSearch analytics sink adapters with lifecycle/idempotency tracking, opt-in external temporal/log report query paths, and a lightweight in-memory store for explicit tests/local experimentation.
- `apps/workers`: Python log-analysis pipeline plus Temporal workflow/activity worker for ingestion, multi-line merge, timestamp parsing, redaction, templating, representative sampling, model annotation, label broadcasting, temporal aggregation, candidate causal graph generation with PGEM-style and Granger-style evidence, evidence-packet causal summary generation through the model gateway, cautious fallback summary rendering, and export generation.
- `apps/web`: Next.js/React/TypeScript operational workbench shell aligned to final API shapes, with Apache ECharts for Temporal View stacked time windows and Cytoscape.js for the directed Causal Graph.
- `infra/docker`: Dockerfiles for web, API, and worker. The web image builds the Next.js app and
  serves it with `next start` rather than the development server; API containers expose `/healthz`
  and honor `LOGAN_API_WORKERS` for Uvicorn process count.
- `infra/k8s`: coherent Kubernetes manifests for namespace, config, secrets examples, deployments, services, ingress, PVCs, migration job, and network policy.

### Deployment Architecture

```mermaid
flowchart LR
    user["Support / SRE user"] --> browser["Browser"]
    browser --> web["Next.js workbench"]
    web --> api["FastAPI API"]

    api --> auth["Session auth / RBAC"]
    api --> meta["SQLAlchemy metadata store"]
    meta --> sqlite["SQLite local default"]
    meta --> postgres["PostgreSQL compose / production"]

    api --> objects["Object storage"]
    objects --> localfs["Local object store"]
    objects --> minio["S3 / MinIO uploads"]

    api --> orchestrator["Analysis orchestrator"]
    orchestrator --> localrun["Local synchronous run"]
    orchestrator --> temporal["Temporal workflow"]
    temporal --> worker["Python analysis worker"]
    localrun --> pipeline["LogAn analysis pipeline"]
    worker --> pipeline

    pipeline --> artifacts["Step artifact manifests"]
    pipeline --> reports["Report data"]
    reports --> views["Summary / Temporal / Logs / Causal Graph / Causal Summary"]
    views --> web

    pipeline --> sinks["Optional analytics sinks"]
    sinks --> clickhouse["ClickHouse"]
    sinks --> opensearch["OpenSearch"]
    api --> aiplatform["AI Platform chat completions"]
    pipeline --> aiplatform

    api --> metrics["Prometheus metrics"]
    api --> traces["OpenTelemetry traces"]
```

## Local Setup

Python 3.11+ is required. Node 20.9+ with npm is recommended for the web workspace.
For platform-specific setup, see
[`docs/install-test-windows-macos.md`](docs/install-test-windows-macos.md).

### Fast Local Install And Test

Use this path when you only need the quickest local confidence check. It installs
the Python package, installs the npm workspace, runs the backend tests, and checks
the web workspace.

Windows PowerShell:

```powershell
cd C:\Work\llm-powered-log-analytic
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e . pytest pytest-asyncio ruff
npm install
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
python -m pytest -q
npm run test --workspace @logan/web
npm run build --workspace @logan/web
```

macOS or Linux shell:

```bash
cd /path/to/llm-powered-log-analytic
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e . pytest pytest-asyncio ruff
npm install
cp -n .env.example .env
python -m pytest -q
npm run test --workspace @logan/web
npm run build --workspace @logan/web
```

Optional browser E2E:

```bash
npm run e2e:install
npm run e2e
```

```bash
python3 -m pip install -e . pytest pytest-asyncio
npm install
```

Drain3 templating is optional because upstream `drain3` pins legacy `jsonpickle`
versions that are not available from every package mirror or Python environment.
The default install uses the deterministic `StableDrainAdapter` fallback. To use
real Drain3 where the dependency set is available, install:

```bash
python3 -m pip install -e ".[drain3]"
```

Copy `.env.example` to `.env` for local services. The tests do not require Docker, AI Platform credentials, or real external services.

## Test Commands

```bash
python3 -m pytest tests
```

Run the deterministic checkout benchmark evaluation:

```bash
python -m logan_workers.evaluation.run \
  --benchmark benchmarks/logan/checkout_incident \
  --out .logan/evaluation/report.json \
  --markdown .logan/evaluation/report.md
```

Optional web checks after installing dependencies:

```bash
npm run test --workspace @logan/web
npm run lint --workspace @logan/web
```

Install the Chromium browser for Playwright once on a workstation or VM:

```bash
npm run e2e:install
```

Run the browser E2E suite from the repository root:

```bash
npm run e2e
```

The Playwright config starts FastAPI on `127.0.0.1:8000` and the Next.js workbench on
`127.0.0.1:3000`. Browser navigation uses `http://localhost:3000`, and the web app uses
`NEXT_PUBLIC_API_BASE_URL=http://localhost:8000` so API cookies and CORS match local browser
behavior. E2E uses `LOGAN_STORE_BACKEND=memory`, `LOGAN_OBJECT_STORE_BACKEND=local`, and
`.logan/e2e-object-store`; the in-memory store is reset when the API process exits. It also sets
`LOGAN_LLM_PROVIDER=mock` so the sample/local analysis path is deterministic and does not require
Docker, AI Platform credentials, MinIO, ClickHouse, OpenSearch, Temporal, or an external
database.

Run the full-stack Docker smoke when Docker resources are available:

```bash
make full-stack-smoke
make full-stack-down
```

The smoke stack starts PostgreSQL, MinIO, ClickHouse, OpenSearch, Temporal, the API, and the
worker. It uses durable SQLAlchemy/PostgreSQL metadata, MinIO presigned uploads, Temporal
orchestration, mock LLM annotation, and real ClickHouse/OpenSearch sink/query paths. It does not
use or require AI Platform credentials.
Docker Compose keeps this PostgreSQL path by using `LOGAN_COMPOSE_DATABASE_URL`, so the default
local SQLite `LOGAN_DATABASE_URL=sqlite:///.logan/logan.db` in `.env` does not affect full-stack
smoke runs.

## Run API and Web Together

Start the FastAPI backend from the repository root:

```bash
uvicorn app.main:app --reload --app-dir apps/api
```

Start the Next.js workbench in another shell:

```bash
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000 npm run dev --workspace @logan/web
```

`NEXT_PUBLIC_API_BASE_URL` defaults to `http://localhost:8000`. Browser API calls use
`credentials: "include"` so the FastAPI `logan_session` cookie is sent to the backend.
Set `LOGAN_CORS_ALLOWED_ORIGINS` on the API to the comma-separated browser origins that may send
credentialed requests, for example `https://logan.example.com,http://localhost:3000`.
Containerized API deployments can set `LOGAN_API_WORKERS` to control Uvicorn worker count.
The default local API uses durable SQLite metadata at `.logan/logan.db`.
Uploaded bytes use the local object store by default and are written under
`.logan/object-store` unless `LOGAN_LOCAL_OBJECT_STORE_DIR` is set.
External analytics sinks and service-backed report queries are disabled by default,
so local runs and tests make no ClickHouse or OpenSearch network calls.

Prometheus metrics are enabled by default at `GET /metrics`. The exposition includes
low-cardinality API request, rate-limit, analysis pipeline, model gateway, and analytics sink
metrics. Labels intentionally avoid tokens, database URLs, object-store secrets, cookies, raw log
text, prompts, case text, and file paths. Set `LOGAN_METRICS_ENABLED=false` to disable the
endpoint or `LOGAN_METRICS_PATH=/internal/metrics` to change its path.

OpenTelemetry FastAPI instrumentation is optional and off by default:

```bash
LOGAN_OTEL_ENABLED=true
LOGAN_OTEL_SERVICE_NAME=logan-api
LOGAN_OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4318/v1/traces
```

If OTEL is disabled or the optional runtime imports are unavailable, the API still starts normally.

## Representative Lines Only

The pipeline never sends every raw log line to a model. It runs this sequence:

1. Stream and preserve raw file path, line number, timestamp, and hash evidence.
2. Merge multi-line stack traces while retaining all original line refs.
3. Redact sensitive values before any model-facing payload is built.
4. Normalize and template logs with a Drain-style adapter.
5. Select a small representative sample set per template.
6. Call the model gateway only with redacted representative samples.
7. Broadcast validated template annotations back to all lines in the same template group.

Tests assert that model inputs are redacted, representative samples are used, and labels are broadcast to enriched log lines.

## Security Notes

- AI Platform is the only production LLM provider (`ai_platform`) and `gpt-5.4` is the default
  model.
- `POST /api/chat/stream` streams authenticated case-workspace answers over SSE using compact redacted analysis context when a case/run is available.
- Tests inject deterministic mocked model gateways through `create_app(...)` or pipeline gateway arguments.
- AI Platform credentials are server-side configuration only and are never returned to frontend responses.
- Sensitive data redaction covers email, IP, bearer tokens, passwords, secrets, API keys, JWTs, UUIDs, card-like values, URL query secrets, and tenant/customer IDs before model calls.
- Causal graph fields use `candidate_cause`, `confidence`, `evidence`, and `needs_validation`; summaries use cautious language.
- PGEM-style transition scores and Granger-style lagged-linear scores are candidate causal evidence only. They help rank directions for validation; they do not prove root cause truth.

## Environment Variables

See `.env.example` for the full list. Key defaults:

- `LOGAN_LLM_PROVIDER=ai_platform`
- `LOGAN_LLM_PROVIDER=mock` is supported for deterministic local/CI E2E analysis only; production
  paths should use `ai_platform`.
- `LOGAN_DATABASE_URL=sqlite:///.logan/logan.db` by default for local durable metadata; set it to another `sqlite:///...` path or `postgresql+psycopg://user:pass@host:5432/db` for PostgreSQL.
- `LOGAN_STORE_BACKEND=auto`; `auto` uses SQLAlchemy with SQLite/PostgreSQL. Use `memory` only for explicit ephemeral tests, or `sqlalchemy` to require a configured database URL.
- `LOGAN_ANALYSIS_ORCHESTRATOR=local`; set to `temporal` to have the API create the SQLAlchemy run and start `AnalyzeCaseWorkflow`.
- `LOGAN_TEMPORAL_ADDRESS=temporal:7233`, `LOGAN_TEMPORAL_NAMESPACE=default`, and `LOGAN_TEMPORAL_TASK_QUEUE=logan-analysis` configure the Temporal API client and worker.
- `LOGAN_TEMPORAL_ACTIVITY_START_TO_CLOSE_SECONDS=3600` and `LOGAN_TEMPORAL_ACTIVITY_MAX_ATTEMPTS=3` are copied into replay-safe workflow params and used for the analysis activity timeout/retry policy.
- `LOGAN_OBJECT_STORE_BACKEND=local`; local uploads store real file bytes on disk and record `file://` object URIs.
- `LOGAN_LOCAL_OBJECT_STORE_DIR=.logan/object-store` relative to the API process working directory by default.
- `LOGAN_ANALYSIS_INPUT_TMP_DIR=.logan/analysis-inputs`; local API analysis and Temporal workers materialize S3/MinIO completed uploads here before pipeline ingestion, then clean up the temporary files.
- `LOGAN_OBJECT_STORE_BACKEND=s3` or `minio` enables presigned S3/MinIO raw uploads; configure `LOGAN_S3_BUCKET`, `LOGAN_S3_ACCESS_KEY`, `LOGAN_S3_SECRET_KEY`, and `LOGAN_S3_ENDPOINT` for MinIO.
- `LOGAN_S3_MULTIPART_THRESHOLD_BYTES=104857600`, `LOGAN_S3_MULTIPART_PART_SIZE_BYTES=67108864`, and `LOGAN_S3_MULTIPART_MAX_PARTS=10000` control S3/MinIO multipart upload planning. Local uploads remain direct authenticated API `PUT` requests.
- `LOGAN_STEP_ARTIFACTS_ENABLED=true` writes one safe `step_manifest` JSON artifact per completed pipeline step.
- `LOGAN_STEP_ARTIFACT_FAILURE_MODE=warn`; use `fail` only when step artifact storage errors should fail analysis runs.
- `LOGAN_AI_PLATFORM_MODEL=gpt-5.4`
- `LOGAN_AI_PLATFORM_REASONING_EFFORT=high`
- `LOGAN_LLM_PROVIDER=ai_platform` routes model calls to AI Platform chat completions.
- `LOGAN_AI_PLATFORM_CHAT_HOST=` and `LOGAN_AI_PLATFORM_CHAT_URI=/v1/api/v1/chat/completions`
  configure the chat endpoint.
- `LOGAN_AI_PLATFORM_TOKEN=` can provide a direct trust token. Alternatively set
  `LOGAN_AI_PLATFORM_USERNAME`, `LOGAN_AI_PLATFORM_PASSWORD`, `LOGAN_AI_PLATFORM_USERCASE`,
  `LOGAN_AI_PLATFORM_IB2B_HOST`, and `LOGAN_AI_PLATFORM_IB2B_URI` to exchange credentials for a
  short-lived JWT.
- `LOGAN_AI_PLATFORM_TRUST_TOKEN_HEADER=X-XXXX-E2E-Trust-Token`,
  `LOGAN_AI_PLATFORM_TRACKING_PREFIX=EFP`, and
  `LOGAN_AI_PLATFORM_MAX_COMPLETION_TOKENS=4096` mirror the AI Platform client defaults.
- `LOGAN_CREDENTIAL_ENCRYPTION_KEY=change-me-local-key`
- `LOGAN_RAW_LOG_RETENTION_DAYS=30`
- `LOGAN_REPORT_RETENTION_DAYS=365`
- `LOGAN_AUDIT_RETENTION_DAYS=730`
- `LOGAN_RATE_LIMIT_ENABLED=false`
- `LOGAN_RATE_LIMIT_REQUESTS_PER_MINUTE=120`
- `LOGAN_LOG_LEVEL=INFO`; set `DEBUG` on API and worker pods while diagnosing deployment issues.
- `LOGAN_METRICS_ENABLED=true`
- `LOGAN_METRICS_PATH=/metrics`
- `LOGAN_OTEL_ENABLED=false`
- `LOGAN_OTEL_SERVICE_NAME=logan-api`
- `LOGAN_OTEL_EXPORTER_OTLP_ENDPOINT=` optional OTLP HTTP trace endpoint.
- `LOGAN_ANALYTICS_SINKS_ENABLED=false`; when true, SQLAlchemy analysis completion may publish redacted analytics payloads to configured external sinks.
- `LOGAN_CLICKHOUSE_URL=` optional ClickHouse HTTP endpoint.
- `LOGAN_CLICKHOUSE_DATABASE=logan`
- `LOGAN_CLICKHOUSE_USERNAME=` and `LOGAN_CLICKHOUSE_PASSWORD=` optional HTTP basic auth.
- `LOGAN_OPENSEARCH_URL=` optional OpenSearch endpoint.
- `LOGAN_OPENSEARCH_USERNAME=` and `LOGAN_OPENSEARCH_PASSWORD=` optional HTTP basic auth.
- `LOGAN_EXTERNAL_ANALYTICS_QUERIES_ENABLED=false`; when true, SQLAlchemy temporal and log table reports may query ClickHouse/OpenSearch first, but only when the matching URL is configured and the run has a succeeded `analytics_sink_writes` record for that external target.
- `LOGAN_EXTERNAL_ANALYTICS_QUERY_TIMEOUT_SECONDS=10`
- `LOGAN_ANALYTICS_SINK_FAILURE_MODE=warn`; use `fail` to make sink publish errors fail the analysis run. SQLAlchemy-backed sink writes are tracked per external target in `analytics_sink_writes`, so succeeded targets are skipped on re-publish and failed targets are retried on the next completion attempt.
- `NEXT_PUBLIC_API_BASE_URL=http://localhost:8000` for the web workspace API base URL.

Full-stack smoke helper variables are optional and used only by `scripts/full_stack_smoke.py` or
`tests/integration/test_full_stack_smoke.py`:

- `LOGAN_RUN_FULL_STACK_SMOKE=true` enables the pytest wrapper.
- `LOGAN_FULL_STACK_API_BASE_URL=http://localhost:8000`
- `LOGAN_FULL_STACK_S3_ENDPOINT=http://localhost:9000`
- `LOGAN_FULL_STACK_S3_PUBLIC_ENDPOINT=http://localhost:9000` rewrites container presigned URLs
  when running the script from the host.
- `LOGAN_FULL_STACK_DATABASE_URL=postgresql+psycopg://logan:logan@localhost:5432/logan`
- `LOGAN_FULL_STACK_CLICKHOUSE_URL=http://localhost:8123`
- `LOGAN_FULL_STACK_OPENSEARCH_URL=http://localhost:9200`

## Roadmap

Remaining staged work is tracked in `docs/operations.md`. The main gaps are advanced policy groups/SCIM integration and continued E2E expansion for enterprise workflows.
