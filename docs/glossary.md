# Glossary

Domain vocabulary used across the code, API, and UI. For how these concepts connect end to end,
read [life-of-a-log-line.md](life-of-a-log-line.md).

## Cases and access

- **Case** — one incident investigation: title, issue description, product/service/environment,
  incident window, uploads, and analysis runs. Created by a user, scoped to an organization.
- **Organization** — tenant boundary for users, cases, and policy groups.
- **Collaborator** — per-case access grant (`viewer`/`editor`/`owner`) in `case_collaborators`.
  The case creator is an implicit owner.
- **Policy group** — organization-scoped group that can grant case access
  (`case_group_access`); SCIM provisioning writes to the same tables.

## Analysis run lifecycle

- **Analysis run** — one execution of the pipeline over a case's uploaded files. Status moves
  queued → processing → completed/failed/cancelled. The full result is serialized on
  `analysis_runs.result_json` and fanned out into normalized tables.
- **Orchestrator** — `local` runs the pipeline synchronously inside the API process;
  `temporal` starts `AnalyzeCaseWorkflow` on a Temporal cluster and a worker executes the same
  pipeline durably.
- **Job event** — append-only progress row per pipeline step
  (`started`/`completed`/`failed`), deduplicated by idempotency key, with **count-only**
  metadata. Powers the progress panel.
- **Step artifact / step manifest** — one small JSON manifest written to object storage per
  completed step, tracked in `analysis_step_artifacts`. Contains counts and ids only — never
  raw log text or prompts.

## Log processing

- **Raw file / raw log line** — uploaded bytes and their lines, preserved with `file_path`,
  `line_number`, and sha256 hash evidence.
- **Multi-line merge** — stack traces and continuation lines are merged into one logical entry
  while retaining every original line reference.
- **Redaction** — masking of emails, IPs, bearer tokens, passwords, secrets, API keys, JWTs,
  UUIDs, card-like values, URL query secrets, and tenant/customer ids **before** any
  model-facing payload is built (`algorithms/redactors.py`).
- **Normalized log line** — the parsed, redacted representation: timestamp, level, service,
  message, evidence ref.
- **Log template** — the cluster a line belongs to after Drain-style templating; variable
  tokens become `<*>` (e.g. `error gateway request_id=<*> post /checkout failed status=<*>`).
  Default adapter is the deterministic `StableDrainAdapter`; real Drain3 is an optional extra.
- **Representative sample** — a handful of lines chosen per template (default 5). Only these
  redacted samples are ever sent to the model.
- **Annotation** — the model's classification of one template: golden signal, fault
  categories, entities, severity, confidence, rationale. Produced once per template, then
  **broadcast** to every line in that template group.
- **Golden signal** — one of `error`, `availability`, `latency`, `saturation`, `traffic`,
  `information`, `unknown` (`logan_workers/models.py`). Everything except
  `information`/`unknown` counts as an **offending signal** and feeds temporal/causal analysis.
- **Fault category** — free-form failure taxonomy tags, e.g. `application`, `database`,
  `dependency`, `resource`, `timeout`, `network`.
- **Entities** — structured mentions extracted per template: services, source/target service,
  database, status codes, durations, source IPs.

## Temporal and causal analysis

- **Time window signal** — per-window aggregation (default 60s) of line counts by golden
  signal/service; rendered as the stacked Temporal View.
- **Causal graph** — directed **candidate** relationships between offending templates. Fields
  are deliberately hedged: `candidate_cause`, `confidence`, `evidence`, `needs_validation`.
- **Temporal precedence** — evidence that the source template's activity consistently starts
  before the target's.
- **Lift** — how much the target's rate increases when the source is active versus its baseline.
- **Lagged correlation** — correlation between source and target count series at a time offset.
- **PGEM-style score** — directed transition evidence built from source support, target
  coverage, baseline-rate lift, and median lag.
- **Granger-style score** — checks whether lagged source counts improve target-count prediction
  over a target-history baseline, with Benjamini-Hochberg adjustment across tested directions.
- **PageRank centrality** — graph-position evidence over the candidate edges.
- **Root-cause candidate** — highest-ranked source node(s); a validation aid, never proof.
- **Causal summary** — evidence-first narrative built from an evidence packet through the model
  gateway, with a deterministic cautious fallback when the model is unavailable. Includes
  `next_actions` and `evidence_refs`.
- **Evidence ref** — the traceability tuple carried by every derived object: `case_id`,
  `analysis_run_id`, `template_id`, `log_id`, `file_path`, `line_number`, `timestamp`.

## Model access

- **Model gateway** — the seam for all model calls. Production: `AIPlatformModelGateway`
  (chat completions, trust token or iB2B credential exchange). Local/CI:
  `MockAIPlatformAnnotationGateway`, a deterministic keyword classifier.
- **Annotation budget** — optional caps on templates annotated per run and sample size/length
  (`inference.max_annotation_templates` etc. in the run config).

## Storage and reporting

- **Metadata store** — the `MetadataStore` surface with two implementations kept
  behavior-identical: in-memory (tests) and SQLAlchemy (SQLite/PostgreSQL).
- **Fan-out tables** — normalized rows written on completion (templates, samples, annotations,
  window signals, causal nodes/edges/summaries…) that serve the five report endpoints.
- **Analytics sinks** — optional post-completion publishing of whitelisted redacted payloads to
  ClickHouse (`enriched_log_lines`, `window_aggregates`) and/or OpenSearch (run-scoped index).
  Each target write is recorded idempotently in `analytics_sink_writes`.
- **External analytics queries** — opt-in read path where temporal/log reports query
  ClickHouse/OpenSearch first and fall back to SQL; only allowed after a succeeded sink write.
- **Exports** — Markdown/HTML/JSON report artifacts generated as the final pipeline step.
- **Retention** — scheduled scrubbing: raw text is replaced by a retained marker while
  normalized evidence rows are preserved (see `docs/security.md`).

## Evaluation

- **Checkout incident benchmark** — deterministic labeled fixture
  (`benchmarks/logan/checkout_incident`) run with the mock gateway; thresholds cover
  review-load reduction, golden-signal/fault-category F1, entity F1, root-cause hit@k, useful
  causal-edge recall, and a summary rubric. Non-zero CLI exit is a release blocker for
  pipeline changes.
- **Review-load reduction** — fraction of raw lines a reviewer no longer needs to read because
  template grouping and annotation collapse them.
- **Mock SSO** — local-only identity provider built into the API (`/api/auth/sso/mock/*`) that
  issues a dev user without credentials; forbidden in production.
