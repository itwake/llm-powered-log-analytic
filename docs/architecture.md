# Architecture

LogAn has two runtime processes. The API contains an internal Python analysis package:

```text
Next.js web ──HTTP──> FastAPI
                       ├── SQLAlchemy ──> SQLite or PostgreSQL
                       ├── local filesystem
                       ├── model gateway
                       └── AnalyzeCasePipeline (in process)
```

SQLite and PostgreSQL use one SQLAlchemy store. Uploaded logs and safe step manifests use one
local filesystem implementation. Analysis runs in the API process. Prometheus is the single
observability integration.

## Analysis flow

```text
files
  -> ingest and sha256
  -> multiline merge
  -> timestamp parse, normalization, redaction
  -> StableDrainAdapter templates
  -> representative sampling
  -> model annotation of redacted representatives
  -> label broadcast
  -> time-window aggregation
  -> candidate causal graph and ranking
  -> cautious causal summary
  -> Markdown, HTML, and JSON exports
```

Each step emits progress events. The API persists safe event metadata and normalized result rows.
Step manifests contain identifiers, timestamps, status, and sanitized counts; they exclude raw
logs, prompts, model inputs, credentials, tokens, cookies, database URLs, and full paths.

## Boundaries

- `apps/web` contains presentation and API clients only.
- `apps/api` owns HTTP, authentication, authorization, configuration, persistence, and runtime
  composition.
- `apps/api/logan_analysis` owns analysis models and algorithms and has no dependency on `app`.
- `ModelGateway` is the only model-provider port.
- `MetadataStore` has one implementation: `SQLAlchemyStore`.

The UI’s “Temporal View” is a time-window visualization and is unrelated to workflow
orchestration.

## Evidence

Every causal relationship is candidate evidence with confidence and `needs_validation`. Time
precedence, lift, lagged correlation, PGEM-style, Granger-style, and PageRank-style scores assist
ranking; they do not assert definitive causation.
