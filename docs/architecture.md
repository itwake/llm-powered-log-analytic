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
  -> mocked GitHub Copilot annotation on redacted representatives only
  -> label broadcasting
  -> temporal aggregation
  -> candidate causal graph with evidence and PageRank-style ranking
  -> cautious causal summary
  -> Markdown, HTML, JSON exports
```

Production adapters are represented by SQLAlchemy models, migration DDL, Docker Compose services, and Kubernetes manifests. Metadata can run against SQLite or PostgreSQL through SQLAlchemy; tests can still inject the deterministic in-memory store so no Docker services are required.

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
- Replace synchronous orchestration with Temporal workflow activities.
- Replace mock Copilot gateway with source-token to Copilot-plugin token exchange and `/responses` calls.
- Extend causal methods with PGEM and Granger implementations while retaining bin-size sensitivity checks.
