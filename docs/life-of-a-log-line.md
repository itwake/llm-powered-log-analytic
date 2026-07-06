# Life of a Log Line

The fastest way to understand LogAn is to follow one line through the whole system. Our
protagonist is a real line from the bundled sample incident
(`tests/fixtures/logs/checkout_incident/gateway.log`):

```text
2026-06-06T10:12:31Z ERROR gateway request_id=req-1 POST /checkout failed status=500 duration_ms=31000
```

The scenario: auth-service's database pool saturates, payment-service times out calling
auth-service, and the gateway starts returning 500s on checkout. Our line is a symptom — the
interesting question the pipeline must answer is *what it is a symptom of*.

Terms in **bold** are defined in the [glossary](glossary.md).

## 1. Upload

A user creates a **case** and uploads `gateway.log` (workbench dropzone, or
`scripts/seed_demo_case.py`). The API stores the bytes through the object store
(`apps/api/app/services/object_store.py`) — local disk under `.logan/object-store` by default,
S3/MinIO presigned uploads in production — and records a `raw_files` row. Nothing has parsed
the line yet.

## 2. Analysis starts

`POST /api/cases/{case_id}/analysis-runs` creates an **analysis run**. With the default
`local` **orchestrator** the API runs `AnalyzeCasePipeline`
(`apps/workers/logan_workers/pipeline.py`) synchronously; with `temporal` a worker executes the
same pipeline durably. Every step below emits `started`/`completed` **job events** with
count-only metadata, which the workbench progress panel polls.

## 3. Ingestion — `activities/ingestion.py`

The file is streamed line by line. Our line becomes a record carrying its identity forever:
`file_path=gateway.log`, `line_number` (say 4), a sha256 hash, and the raw text. Gzip, zip,
and JSONL inputs are unwrapped here too.

## 4. Multi-line merge — `activities/preprocessing.py`, `algorithms/multiline.py`

Stack traces and continuation lines are merged into single logical entries, keeping every
original line reference. Our line is a single-line entry, so it passes through unchanged.

## 5. Parse, normalize, redact — `activities/preprocessing.py`, `algorithms/redactors.py`

The timestamp (`2026-06-06T10:12:31Z`), level (`ERROR`), and service (`gateway`) are parsed
out. **Redaction** then masks emails, IPs, tokens, UUIDs, and other sensitive values in the
message — before anything model-facing exists. The result is a **normalized log line** with an
**evidence ref** pointing back to file and line number.

## 6. Templating — `activities/templating.py`, `algorithms/drain_adapter.py`

Drain-style clustering groups lines by structure. Variable tokens collapse to `<*>`, so our
line lands in the **template**:

```text
<*>-<*>-06t10:<*>:31z error gateway request_id=<*> post /checkout failed status=<*> duration_ms=<*>
```

Both `req-1 ... 31000` and `req-2 ... 30500` map here. This is the pivotal compression step:
from now on the pipeline mostly reasons about a handful of templates instead of every line.

## 7. Representative sampling — `activities/sampling.py`

Up to five **representative samples** are selected per template. If our line is picked, its
redacted text will represent the whole group; if not, it will still inherit everything decided
about the template.

## 8. Annotation — `activities/inference.py`, `prompts/annotation_prompt.md`

For each template, a payload of template text + redacted samples (plus case context) goes to
the **model gateway** — AI Platform in production, the deterministic mock locally. This is the
**only** place log-derived text reaches a model, and only the redacted representatives. The
model returns the **annotation** for our template:

- **golden signal**: `error`, **fault categories**: `["application"]`
- **entities**: service `gateway`, status code `500`, URL path `/checkout`
- severity, confidence, and a rationale

## 9. Broadcasting — `activities/broadcasting.py`

The annotation is copied to every line in the template group. Our specific line — even if it
was never sampled — is now an annotated, enriched log line, and shows up filtered and labeled
in the **Tabular Logs** view.

## 10. Temporal aggregation — `activities/temporal_aggregation.py`

Lines are bucketed into 60-second **time window signals** by golden signal and service. Our
line contributes one `error`/`gateway` count to the `10:12` window. The stacked bars in
**Temporal View** are exactly these rows; clicking a bar deep-links into Tabular Logs with
that window as a filter.

## 11. Causal graph — `activities/causal.py`, `algorithms/causal_*.py`

Offending templates (golden signal ≠ information) become **causal nodes**; directed edges are
scored with **temporal precedence**, **lift**, **lagged correlation**, **PGEM-style**,
**Granger-style**, and **PageRank** evidence. In our incident the auth pool-exhaustion template
precedes and predicts payment timeouts, which precede our gateway-500 template — so the graph
proposes `auth pool exhausted → payment timeout → gateway 500`, each edge carrying
`candidate_cause`, `confidence`, `evidence`, and `needs_validation: true`. The **Causal Graph**
view renders exactly this. Our line's role: its template is the *effect* end of the chain, and
its evidence refs make the edge clickable down to raw lines.

## 12. Causal summary — `activities/summary.py`, `prompts/causal_summary_prompt.md`

An evidence packet (top nodes, edges, windows — ids and redacted template text only) goes
through the model gateway to produce the **Causal Summary**: a cautious narrative naming
auth-service pool saturation as the leading **root-cause candidate**, with `next_actions` and
`evidence_refs`. If the model is unavailable, a deterministic fallback renders the same
evidence without narrative flourish.

## 13. Exports and persistence

`export_analysis` renders Markdown/HTML/JSON reports. On completion the store fans the result
out into normalized tables (`normalized_log_lines`, `log_templates`, `template_annotations`,
`time_window_signals`, `causal_*`, …) that back the five report endpoints, writes one safe
**step manifest** per step, and — if enabled — publishes redacted rows to ClickHouse/OpenSearch
**analytics sinks**.

## Where our line ended up

| Surface | What our line became |
| --- | --- |
| Data Summary | one count in totals and the `error` signal breakdown |
| Temporal View | +1 in the `10:12` error/gateway bar |
| Tabular Logs | a filterable row labeled error/application with entities |
| Causal Graph | evidence behind the `payment timeout → gateway 500` edge |
| Causal Summary | a cited evidence ref under the root-cause narrative |
| Exports / sinks | a redacted normalized row with full traceability |

At every hop it kept its `file_path`, `line_number`, hash, and timestamp — so any conclusion in
any view can be walked back to the exact raw line it came from. That traceability, and the rule
that models only ever see redacted representatives, are the two invariants the whole design
hangs on.
