# Architecture

LogAn is organized as a monorepo with three runtime surfaces:

- FastAPI backend for auth, Copilot authorization, cases, uploads, analysis runs, reports, feedback, chat, tasks, and capabilities.
- Python worker package for deterministic log analysis and future Temporal activities.
- Next.js web workbench for operational incident review.

The tested stage path runs synchronously:

```text
case files
  -> ingestion and sha256
  -> multi-line merge with original line refs
  -> timestamp parse, normalization, redaction
  -> Drain-style templating
  -> representative sampling
  -> GitHub Copilot Plugin annotation on redacted representatives only
  -> label broadcasting
  -> temporal aggregation
  -> candidate causal graph with evidence and PageRank-style ranking
  -> cautious causal summary
  -> Markdown, HTML, JSON exports
```

Production adapters are represented by SQLAlchemy models, migration DDL, Docker Compose services, and Kubernetes manifests. Metadata can run against SQLite or PostgreSQL through SQLAlchemy. Uploaded bytes use a local disk object store by default, so tests can still inject the deterministic in-memory store, fake device-code client, and mock model gateway with no Docker services or external model network required.

The API owns runtime injection points on app state:

- `copilot_auth_client` defaults to the real GitHub device-code client.
- `model_gateway` defaults to the real GitHub Copilot `/responses` gateway.
- tests pass deterministic fakes through `create_app(...)`.

The Copilot gateway resolves stored plugin credentials, stored GitHub source OAuth credentials, and optional server-side environment tokens. Source tokens are exchanged for Copilot plugin tokens before calling `/responses`; no token material crosses the frontend boundary.

## Traceability

Every pipeline object carries evidence references with:

- `case_id`
- `analysis_run_id`
- `template_id`
- `log_id`
- `file_path`
- `line_number`
- `timestamp`

Causal edges are candidate relationships only. API and worker fields use `candidate_cause`, `confidence`, `evidence`, and `needs_validation`.

## Extension Seams

- Replace `StableDrainAdapter` with `drain3` behind the same `cluster()` interface.
- Fan out metadata-backed analysis results into ClickHouse, OpenSearch, and S3 object storage adapters.
- Add S3/MinIO presigned uploads and resumable/multipart support behind the object-store seam.
- Replace synchronous orchestration with Temporal workflow activities.
- Add streaming Copilot `/responses` and `/api/chat/stream` SSE support.
- Add Copilot plugin-token expiry caching and revocation flows.
- Extend causal methods with PGEM and Granger implementations while retaining bin-size sensitivity checks.
