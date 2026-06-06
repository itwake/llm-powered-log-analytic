# LogAn Platform

LogAn is a case-based incident log diagnosis platform for Support, SRE, and development teams. Users create an incident case, upload related logs, run an analysis, and review five linked views: Data Summary, Temporal View, Tabular Logs, Causal Graph, and Causal Summary.

This repository is the staged foundation for the final product. The current implementation includes a runnable FastAPI backend, durable SQLAlchemy metadata store with an in-memory test option, local object-byte uploads, synchronous worker pipeline, synthetic checkout incident fixtures, tests, a Next.js workbench shell, and deployment scaffolding.

## Architecture

- `apps/api`: FastAPI API, Pydantic v2 schemas, auth/session handling, real GitHub Copilot device-code auth, Copilot `/responses` gateway, SQLAlchemy metadata persistence, and a lightweight in-memory store for explicit tests/local experimentation.
- `apps/workers`: Python log-analysis pipeline for ingestion, multi-line merge, timestamp parsing, redaction, templating, representative sampling, model annotation, label broadcasting, temporal aggregation, candidate causal graph generation, causal summary rendering, and export generation.
- `apps/web`: Next.js/React/TypeScript operational workbench shell aligned to final API shapes.
- `infra/docker`: first-pass Dockerfiles for web, API, and worker.
- `infra/k8s`: coherent Kubernetes manifests for namespace, config, secrets examples, deployments, services, ingress, PVCs, migration job, and network policy.

## Local Setup

Python 3.11+ is required. Node 20+ with pnpm is recommended for the web workspace.

```bash
python3 -m pip install -e . pytest pytest-asyncio
corepack enable
corepack prepare pnpm@10.13.1 --activate
pnpm install
```

Copy `.env.example` to `.env` for local services. The tests do not require Docker, GitHub Copilot credentials, or real external services.

## Test Commands

```bash
python3 -m pytest tests
```

Optional web checks after installing dependencies:

```bash
pnpm --filter @logan/web test
pnpm --filter @logan/web lint
```

## Run API and Web Together

Start the FastAPI backend from the repository root:

```bash
uvicorn app.main:app --reload --app-dir apps/api
```

Start the Next.js workbench in another shell:

```bash
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000 corepack pnpm --filter @logan/web dev
```

`NEXT_PUBLIC_API_BASE_URL` defaults to `http://localhost:8000`. Browser API calls use
`credentials: "include"` so the FastAPI `logan_session` cookie is sent to the backend.
The default local API uses in-memory metadata unless `LOGAN_DATABASE_URL` is set.
Uploaded bytes use the local object store by default and are written under
`.logan/object-store` unless `LOGAN_LOCAL_OBJECT_STORE_DIR` is set.

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

- GitHub Copilot is the default LLM provider (`github_copilot`) and `gpt-5.4` is the default model.
- The default backend LLM runtime is GitHub Copilot Plugin `/responses`; OpenAI and Anthropic fallbacks are not configured.
- Tests inject deterministic mocked Copilot auth and model gateways through `create_app(...)` or pipeline gateway arguments.
- GitHub source OAuth and Copilot plugin tokens are encrypted at rest, decrypted only in backend services, and never returned to frontend responses.
- Sensitive data redaction covers email, IP, bearer tokens, passwords, secrets, API keys, JWTs, UUIDs, card-like values, URL query secrets, and tenant/customer IDs before model calls.
- Causal graph fields use `candidate_cause`, `confidence`, `evidence`, and `needs_validation`; summaries use cautious language.

## Environment Variables

See `.env.example` for the full list. Key defaults:

- `LOGAN_LLM_PROVIDER=github_copilot`
- `LOGAN_DATABASE_URL=` unset by default for lightweight local memory mode; set to `sqlite:///...` for local durable tests or `postgresql+psycopg://user:pass@host:5432/db` for PostgreSQL.
- `LOGAN_STORE_BACKEND=auto`; `auto` uses SQLAlchemy when `LOGAN_DATABASE_URL` is set and memory otherwise. Use `memory` or `sqlalchemy` to force a backend.
- `LOGAN_OBJECT_STORE_BACKEND=local`; local uploads store real file bytes on disk and record `file://` object URIs.
- `LOGAN_LOCAL_OBJECT_STORE_DIR=.logan/object-store` relative to the API process working directory by default.
- `LOGAN_COPILOT_MODEL=gpt-5.4`
- `LOGAN_COPILOT_REASONING_EFFORT=high`
- `LOGAN_COPILOT_OAUTH_CLIENT_ID=Iv1.b507a08c87ecfe98`
- `LOGAN_GITHUB_COPILOT_TOKEN=` optional server-side Copilot plugin token for tests/dev.
- `LOGAN_GITHUB_SOURCE_TOKEN=` optional server-side GitHub source OAuth/PAT token for tests/dev; it is exchanged for a Copilot plugin token per call.
- `LOGAN_COPILOT_BASE_URL=` optional override for the Copilot API base URL.
- `LOGAN_COPILOT_TIMEOUT_SECONDS=30`
- `LOGAN_CREDENTIAL_ENCRYPTION_KEY=change-me-local-key`
- `LOGAN_RAW_LOG_RETENTION_DAYS=30`
- `LOGAN_REPORT_RETENTION_DAYS=365`
- `LOGAN_AUDIT_RETENTION_DAYS=730`
- `NEXT_PUBLIC_API_BASE_URL=http://localhost:8000` for the web workspace API base URL.

## Roadmap

Remaining staged work is tracked in `docs/operations.md`. The main gaps are Copilot plugin-token expiry caching/revocation, `/api/chat/stream` SSE wiring, ClickHouse/OpenSearch fan-out for analysis artifacts, S3/MinIO presigned object-store adapters, resumable/multipart uploads, Temporal activity idempotency backed by durable state, RBAC policy expansion, Playwright e2e coverage, richer chart/graph libraries, and production observability wiring.
