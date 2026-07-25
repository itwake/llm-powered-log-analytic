# Data model

`SQLAlchemyStore` is the single persistence implementation. SQLite is used by default and for
isolated tests; PostgreSQL uses the same domain operations.

Core tables cover:

- organizations, users, sessions, credentials, policy groups, and case access
- cases, collaborators, uploaded raw files, and analysis runs
- job events and safe step-artifact metadata
- normalized log lines, templates, annotations, window aggregates, causal nodes and edges
- summary sections, evidence references, exports, feedback, and audit logs

The analysis completion transaction fans one `AnalysisResult` into normalized rows. Report
endpoints read those rows and keep case/run/organization scoping in every query.

Uploaded bytes and step-manifest bodies are stored on the local filesystem; SQL stores their
internal file URI, digest, size, content type, and lifecycle metadata.

Raw text has shorter retention than normalized reports. Events, audits, metrics, and manifests
allow only sanitized metadata. Model inputs, prompts, credentials, tokens, cookies, and encryption
material are never persisted in those surfaces.

PostgreSQL applies numbered, checksummed migrations in order.
