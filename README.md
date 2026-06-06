# LogAn Platform

LogAn is a case-based incident log diagnosis platform for Support, SRE, and development teams. Users create an incident case, upload related logs, run an analysis, and review five linked views: Data Summary, Temporal View, Tabular Logs, Causal Graph, and Causal Summary.

This repository is the staged foundation for the final product. The current implementation includes a runnable FastAPI backend, durable SQLAlchemy metadata store with an in-memory test option, synchronous worker pipeline, synthetic checkout incident fixtures, tests, a Next.js workbench shell, and deployment scaffolding.

## Architecture

- `apps/api`: FastAPI API, Pydantic v2 schemas, auth/session handling, mocked GitHub Copilot device-code auth for local tests, SQLAlchemy metadata persistence, and a lightweight in-memory store for explicit tests/local experimentation.
- `apps/workers`: Python log-analysis pipeline for ingestion, multi-line merge, timestamp parsing, redaction, templating, representative sampling, mock annotation, label broadcasting, temporal aggregation, candidate causal graph generation, causal summary rendering, and export generation.
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
- Tests use deterministic mocked Copilot auth and model gateways.
- Token-like values are encrypted or mock-encrypted in the local store and are never returned to frontend responses.
- Sensitive data redaction covers email, IP, bearer tokens, passwords, secrets, API keys, JWTs, UUIDs, card-like values, URL query secrets, and tenant/customer IDs before model calls.
- Causal graph fields use `candidate_cause`, `confidence`, `evidence`, and `needs_validation`; summaries use cautious language.

## Environment Variables

See `.env.example` for the full list. Key defaults:

- `LOGAN_LLM_PROVIDER=github_copilot`
- `LOGAN_DATABASE_URL=` unset by default for lightweight local memory mode; set to `sqlite:///...` for local durable tests or `postgresql+psycopg://user:pass@host:5432/db` for PostgreSQL.
- `LOGAN_STORE_BACKEND=auto`; `auto` uses SQLAlchemy when `LOGAN_DATABASE_URL` is set and memory otherwise. Use `memory` or `sqlalchemy` to force a backend.
- `LOGAN_COPILOT_MODEL=gpt-5.4`
- `LOGAN_COPILOT_REASONING_EFFORT=high`
- `LOGAN_CREDENTIAL_ENCRYPTION_KEY=change-me-local-key`
- `LOGAN_RAW_LOG_RETENTION_DAYS=30`
- `LOGAN_REPORT_RETENTION_DAYS=365`
- `LOGAN_AUDIT_RETENTION_DAYS=730`

## Roadmap

Remaining staged work is tracked in `docs/operations.md`. The main gaps are ClickHouse/OpenSearch fan-out for analysis artifacts, real S3/MinIO object bytes and presigned uploads, real Copilot token exchange/runtime calls, Temporal activity idempotency backed by durable state, RBAC policy expansion, Playwright e2e coverage, and production observability wiring.
