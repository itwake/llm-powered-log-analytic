# Reliability and Explainability

LogAn uses an LLM, but its trustworthiness does not rest on trusting model output. The platform
is built so that **deterministic algorithms decide the facts and the model only classifies and
narrates**, every user-facing claim is **traceable to a specific redacted log line**, quality is
**measured by a threshold-gated benchmark**, and every model call has a **deterministic fallback**.
This document explains how to state that reliability story and how the explainability is realized in
code, with pointers for auditors and reviewers.

For where these steps sit in the flow, see [`life-of-a-log-line.md`](life-of-a-log-line.md); for the
redaction guarantees see [`security.md`](security.md); for the benchmark runbook see
[`operations.md`](operations.md).

## Design stance: the model explains, the algorithms decide

The analysis pipeline (`apps/workers/logan_workers/pipeline.py`) has 11 steps. Only **two** call the
model gateway; the rest are deterministic:

| # | Step | Model? | Produces |
| --- | --- | --- | --- |
| 1 | `ingest_paths` | no | raw lines with hash evidence and line refs |
| 2 | `merge_entries` | no | multi-line stack traces merged, original refs retained |
| 3 | `preprocess_redact` | no | redacted / normalized message (before any model payload) |
| 4 | `drain_templating` | no | Drain-style templates over redacted text |
| 5 | `representative_sampling` | no | a small sample set per template |
| 6 | `ai_platform_annotation` | **yes** | per-template golden signal / fault categories / entities |
| 7 | `broadcast_annotations` | no | template labels copied to every line in the group |
| 8 | `temporal_aggregation` | no | fixed time-window counts |
| 9 | `causal_graph` | no | candidate edges + confidence + root-cause ranking |
| 10 | `causal_summary` | **yes** | evidence-first RCA narrative |
| 11 | `export_artifacts` | no | Markdown / HTML / JSON exports |

A third model touchpoint, case chat (`POST /api/chat/stream`, `apps/api/app/api/chat.py`), answers
questions over an already-computed, redacted analysis result and never re-reads raw logs.

Because causal direction, edge confidence, and root-cause rank are computed by step 9
(`infer_causal_graph` in `apps/workers/logan_workers/activities/causal.py`) and not by the model, a
wrong or hallucinated model response cannot invent a causal link or inflate a confidence score.

## Reliability

### 1. The model's role is confined

Steps 6 and 10 are the only places the model shapes output. Annotation is a bounded classification
task (choose exactly one of seven golden signals). Summary is a rewriting task over a fixed evidence
packet. Neither step is allowed to introduce facts that are not already in the structured evidence.

### 2. Quality is measured by a threshold-gated benchmark

`apps/workers/logan_workers/evaluation/` runs the whole pipeline against a hand-labeled incident
(`benchmarks/logan/checkout_incident/labels.json`) and scores it with standard metrics. Each metric
has a threshold; the run reports `passed` only if **all** thresholds are met, and the CLI exits
non-zero otherwise — a release blocker per [`../CONTRIBUTING.md`](../CONTRIBUTING.md).

| Metric | Measures | Threshold |
| --- | --- | --- |
| `golden_signal_macro_f1` | annotation golden-signal accuracy | ≥ 0.95 |
| `fault_category_micro_f1` / `fault_category_macro_f1` | fault-category multi-label accuracy | ≥ 0.95 |
| `entity_precision` / `entity_recall` / `entity_f1` | entity extraction accuracy | ≥ 0.95 |
| `root_cause_hit_at_3` | true root cause is in the top-3 candidates | = 1.0 |
| `useful_causal_edge_recall` | key causal edges are recovered | ≥ 0.95 |
| `summary_rubric_score` | summary covers required framing terms | ≥ 0.95 |
| `review_load_reduction` | fewer items to review vs raw lines | ≥ 0.25 |

Metric math lives in `evaluation/metrics.py` and the scoring in `evaluation/evaluator.py`. Reports
are intentionally compact and redaction-safe (see [`operations.md`](operations.md)). Run it with:

```bash
python -m logan_workers.evaluation.run --benchmark benchmarks/logan/checkout_incident \
  --out .logan/evaluation/report.json --markdown .logan/evaluation/report.md
```

> **Scope caveat.** The benchmark currently runs the pipeline with the deterministic
> `MockAIPlatformAnnotationGateway`, so it validates the pipeline, the scoring rubric, and the
> caution/evidence invariants reproducibly — not `gpt-5.4`'s live accuracy. To measure the production
> model, run the same harness against the `ai_platform` gateway and expand the labeled corpus beyond
> the single checkout incident. `useful_causal_edge_precision` is reported but intentionally not
> gated.

### 3. Deterministic and reproducible

The mock provider (`MockAIPlatformAnnotationGateway`, `apps/workers/logan_workers/activities/inference.py`)
is pure keyword/regex logic — no randomness, no network, no time dependence — so identical input
yields identical output. Unit tests inject fakes via
`create_app(store, model_gateway=..., s3_client_factory=...)` and never touch the network. Repeatable
output is what makes regressions detectable.

### 4. Layered validation keeps bad output away from users

- **Schema validation.** Annotation output is validated with `TemplateAnnotationResult.model_validate`;
  on failure it falls back to a safe `golden_signal="unknown", confidence=0.0` annotation
  (`activities/inference.py`).
- **Evidence validation.** In `activities/summary.py`, every summary claim must cite an evidence
  `log_id` that was actually provided in the packet; a claim that cites nothing raises and the run
  falls back. This structurally blocks fabricated citations.

### 5. Deterministic fallback: the system works without the model

If the gateway is unavailable or the model output fails schema/evidence validation,
`_fallback_summary` (`activities/summary.py`) renders a cautious RCA **from the structured evidence
alone**, tagged `details.source="fallback"` (vs `"llm"`). The LLM augments the system; it is not a
hard dependency.

### 6. Calibrated caution, enforced in code

Summaries never assert a definitive root cause. `needs_validation` is forced to `True`, and a claim
lacking cautious wording (`candidate`, `likely`, `evidence suggests`, `needs validation`) is
automatically prefixed with `Candidate finding:` (`CausalSummaryClaim` validator in
`activities/summary.py`). Causal edges carry `edge_type="candidate_cause"` (`models.py`). Reliability
here means *not overclaiming*, not *always answering*.

### 7. Human-in-the-loop

Causal summaries are editable by owners/editors via
`PATCH /api/cases/{case_id}/analysis-runs/{run_id}/causal-summary`, and users submit ratings through
`POST /api/cases/{case_id}/feedback` (`apps/api/app/api/reports.py`). Model output is continuously
checked and corrected by operators.

### 8. Data governance reduces the risk surface

Redaction runs at step 3, before any model payload exists; the model only ever sees redacted
representative samples, never full raw logs; and `job_events` / `step_manifest` / metrics / audit
metadata are count-only. See [`security.md`](security.md) and the redaction red lines in
[`../CONTRIBUTING.md`](../CONTRIBUTING.md). Less sensitive data reaching the model is itself a
reliability and privacy property.

## Explainability

The organizing principle: **every output can be traced back through evidence → method → numbers to
the exact log line that produced it.**

### 1. Evidence-first: every claim points at a log line

Claims and next actions carry `evidence_refs`, and an `EvidenceRef` (`models.py`) is a precise
pointer: `case_id`, `analysis_run_id`, `template_id`, `log_id`, `file_path`, `line_number`,
`timestamp`. The summary prompt (`apps/workers/logan_workers/prompts/causal_summary_prompt.md`)
requires that *every causal statement refer to evidence_refs*, and the parser rejects claims that do
not. The workbench renders these as clickable evidence chips that jump to the referenced line.

### 2. White-box causal evidence

Causality is explainable because it is algorithmic, not a black box. A `CausalEdge` (`models.py`)
exposes `method`, `confidence`, `p_value_adj`, `lift`, `temporal_precedence_score`,
`correlation_score`, `lag_seconds`, `support_windows`, an `evidence` dict, and `needs_validation`.
Default methods are `temporal_precedence`, `lagged_correlation`, `lift`, `pgem`, and `granger_linear`,
with PageRank centrality for ranking; `granger_linear` uses a deterministic pure-Python lagged OLS and
Benjamini-Hochberg FDR-adjusted p-values (see [`operations.md`](operations.md)). "Why A → B" is
answerable with concrete statistics.

### 3. Per-annotation rationale, confidence, and provenance

A `TemplateAnnotation` (`models.py`) carries a human-readable `rationale` and a `confidence` alongside
`golden_signal`, `fault_categories`, `entities`, and `severity_score`, plus full provenance:
`model_provider`, `model_name`, `prompt_version`, a stable `annotation_id` (uuid5), and the
`raw_model_response`. Each label has both a "why" and an auditable record of how it was produced.

### 4. Explicit uncertainty

Confidence scores (0–1) appear on annotations, edges, candidates, and summaries; summaries include an
`uncertainties` list and per-claim `needs_validation`. The system states what it is unsure about
rather than hiding it.

### 5. Traceable pipeline and prompt versioning

Every step emits `started`/`completed`/`failed` events and a `step_manifest`; benchmark reports include
per-label match/miss detail (`missing_fault_categories`, `extra_fault_categories`, `hit_rank`). Prompts
are versioned (`annotation_v1`, `causal_summary_v1`) and the raw model response is stored, so "what the
model was asked and answered" is reproducible.

### 6. Audience-appropriate surfaces

The summary produces both `internal_rca_markdown` (full evidence for engineers) and
`customer_update_markdown` (cautious, customer-safe). The workbench presents five linked views —
Summary, Temporal, Logs, Causal Graph, Causal Summary — so the explanation is surfaced, not buried.

## Limitations and hardening roadmap

Stated plainly, because acknowledging them strengthens the reliability claim:

1. **Benchmark uses the mock gateway.** It validates scaffolding and invariants, not the production
   model's accuracy. Run the harness against `ai_platform` to measure `gpt-5.4`.
2. **Narrow labeled set.** One synthetic checkout incident with six templates. Broaden the corpus
   across fault types and service topologies before claiming generalized accuracy.
3. **`summary_rubric_score` is term coverage, not semantic correctness.** Consider an LLM-as-judge or
   human review pass for semantic quality.
4. **Single attempt, no retry.** A transient model error goes straight to the deterministic fallback;
   add backoff/retry if the SLA requires it.

## Where the guarantees live (quick reference)

| Guarantee | Code |
| --- | --- |
| LLM confined to 2 of 11 steps | `apps/workers/logan_workers/pipeline.py` |
| Causal facts are algorithmic | `apps/workers/logan_workers/activities/causal.py`, `algorithms/causal_*.py`, `algorithms/pagerank.py` |
| Gated benchmark + metrics | `apps/workers/logan_workers/evaluation/`, `benchmarks/logan/checkout_incident/labels.json` |
| Deterministic mock provider | `apps/workers/logan_workers/activities/inference.py` |
| Annotation schema fallback | `apps/workers/logan_workers/activities/inference.py` |
| Summary evidence validation + fallback | `apps/workers/logan_workers/activities/summary.py` |
| Enforced cautious language | `apps/workers/logan_workers/activities/summary.py`, `prompts/causal_summary_prompt.md` |
| Evidence pointers | `EvidenceRef` in `apps/workers/logan_workers/models.py` |
| White-box causal evidence | `CausalEdge` in `apps/workers/logan_workers/models.py` |
| Annotation provenance | `TemplateAnnotation` in `apps/workers/logan_workers/models.py` |
| Human-in-the-loop | `apps/api/app/api/reports.py` (feedback, causal-summary edit) |
| Redaction before model calls | `apps/workers/logan_workers/activities/preprocessing.py`, `algorithms/redactors.py` |
