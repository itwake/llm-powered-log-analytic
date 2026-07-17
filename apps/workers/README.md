# apps/workers — LogAn Analysis Engine (`logan_workers`)

`apps/workers` is LogAn's Python analysis engine: the deterministic 10-step log-diagnosis pipeline (ingest → redact → template → sample → annotate → causal graph → summary → export) plus its Temporal worker wiring, the mock model gateway, and the offline benchmark harness that gates analysis quality in CI. Given raw log file paths, case context, and a config dict, it produces one `AnalysisResult` — normalized logs, Drain templates, representative samples, model annotations, time-window aggregates, a candidate causal graph with root-cause candidates, a cautious causal summary, and markdown/html/json exports. It owns *all* offline analytics compute for a single analysis run, but not HTTP, persistence, or auth — those live in `apps/api`, which calls this package in-process (local orchestrator) or via a Temporal activity. It also defines the pydantic domain models shared across the platform. Start with the root [README.md](../../README.md) and [CLAUDE.md](../../CLAUDE.md) for the whole-system picture, and [CONTRIBUTING.md](../../CONTRIBUTING.md) for the conventions this app must uphold.

## Tech stack

- Python `>=3.11`, `asyncio` (the pipeline and gateways are async).
- `pydantic` v2 — domain models, validation, JSON serialization.
- `temporalio >=1.7` — worker/workflow/activity (optional; import-shimmed when absent).
- `drain3 >=0.9,<1.0` — optional extra; `StableDrainAdapter` regex fallback when missing.
- Stdlib only for the algorithms: `re`, `statistics`, `math`, `bisect`, `hashlib`, `uuid`, `gzip`/`zip`/`tarfile`.
- `prometheus-client` / `opentelemetry` via the imported `app.observability` helpers.
- `pytest` + `pytest-asyncio` (`asyncio_mode=auto`); `ruff` (line length 100, target `py311`).

There is no per-app package manifest. The repo-root `pyproject.toml` defines a single `logan-platform` distribution whose `[tool.setuptools.packages.find]` scans both `apps/api` and `apps/workers`, so `logan_workers` and `app` install together with `pip install -e .` (add `[drain3]` for the drain3 engine).

## Directory layout

```
apps/workers/logan_workers/
├── pipeline.py              # AnalyzeCasePipeline.run() — the async orchestrator (primary entrypoint)
├── models.py                # all shared pydantic domain models; AnalysisResult output contract
├── temporal_worker.py       # `python -m logan_workers.temporal_worker` — the real worker process
├── temporal_client.py       # start_analyze_case_workflow() — what apps/api calls (orchestrator=temporal)
├── healthcheck.py           # `python -m logan_workers.healthcheck` — Temporal dependency probe
├── activities/              # one thin module per pipeline step; heavy logic delegates to algorithms/
│   ├── ingestion.py preprocessing.py templating.py sampling.py
│   ├── inference.py         # step 6 annotation call + MockAIPlatformAnnotationGateway
│   ├── broadcasting.py temporal_aggregation.py
│   ├── causal.py            # step 9 causal-graph inference (pure)
│   ├── summary.py           # step 10 causal-summary call + deterministic fallback
│   ├── export.py            # export_artifacts (markdown/html/json)
│   └── analysis.py          # the Temporal activity wrapper (loads store, runs pipeline)
├── algorithms/              # pure, dependency-light compute
│   ├── drain_adapter.py redactors.py parsers.py multiline.py representative_sampling.py
│   └── causal_series.py causal_pgem.py causal_granger.py pagerank.py
├── prompts/                 # runtime-read prompt templates (inline fallback if missing)
│   ├── annotation_prompt.md          # annotation_v1
│   └── causal_summary_prompt.md      # causal_summary_v1
├── evaluation/              # offline benchmark harness
│   ├── benchmark.py evaluator.py metrics.py schemas.py reporting.py
│   ├── run.py               # `python -m logan_workers.evaluation.run` (quality gate CLI)
│   └── scale.py             # `python -m logan_workers.evaluation.scale` (synthetic scale bench)
└── workflows/
    └── analyze_case_workflow.py      # replay-safe Temporal workflow + import shims

tests/workers/                       # this app's tests live at repo root, NOT under apps/workers
benchmarks/logan/checkout_incident/  # reference benchmark: manifest.json + labels.json
```

## How it fits

`apps/workers` is not standalone — it is coupled to `apps/api`'s `app` package in one direction, and called by `apps/api` in the other.

- **workers → api (imports):** `pipeline.py` imports `app.observability` (the `record_pipeline_run_*`/`step_*` Prometheus helpers). `activities/analysis.py` imports `app.config.Settings`, `app.sqlalchemy_store.SQLAlchemyStore`, `app.store` helpers (`merge_recorded_progress`, `sanitize_error_message`), and `app.services.analysis_inputs`. So importing `logan_workers.pipeline` pulls in `app.observability`; you cannot ship workers alone.
- **api → workers (calls):** `apps/api` imports `logan_workers.pipeline.AnalyzeCasePipeline` (run in-process by both `store.py` and `sqlalchemy_store.py` when `orchestrator=local`), `logan_workers.temporal_client.start_analyze_case_workflow` (when `orchestrator=temporal`), and `MockAIPlatformAnnotationGateway` (as `_default_model_gateway` in `apps/api/app/main.py` when `LOGAN_LLM_PROVIDER=mock`).

Four contracts define the seams:

| Seam | Where | Contract |
| --- | --- | --- |
| Model gateway | `pipeline.run(gateway=...)` | Duck-typed object with `async responses(**kwargs)`. Mock lives in `activities/inference.py`; the real `AIPlatformModelGateway` lives in `apps/api/app/services/aiplatform_model_gateway.py`, injected via `create_app(model_gateway=...)`. |
| Temporal serialization | `workflows/analyze_case_workflow.py` | Frozen dataclasses `AnalyzeCaseParams` / `AnalyzeCaseResult`. |
| Progress | `progress_callback(event: dict)` | Events carry **count-only** metadata; the store persists them as `job_events`. |
| Output | `models.py` `AnalysisResult` | Consumed by `store.complete_analysis_run`. |

A new pipeline step must also be registered in `PIPELINE_STEP_NAMES` (`apps/api/app/observability.py`) and `PIPELINE_STEPS` (`scripts/full_stack_smoke.py`) or the metric/smoke tests fail.

## Run it locally

There is no standalone pipeline CLI — you exercise it through the benchmark harness, pytest, or the API. All commands run from the repo root (`llm-powered-log-analytic/`).

```bash
# Prereq: install the combined distribution (adds both `app` and `logan_workers`):
python -m pip install -e .            # add [drain3] for the drain3 engine

# Run the deterministic pipeline directly (no services) via its end-to-end test:
python -m pytest tests/workers/test_pipeline.py -q

# Run the real long-running worker (needs a reachable Temporal + LOGAN_DATABASE_URL;
# the process reads env only — load .env into the shell first):
python -m logan_workers.temporal_worker

# Worker dependency healthcheck:
python -m logan_workers.healthcheck --timeout 3

# In practice you exercise the pipeline through the API (default LOGAN_ANALYSIS_ORCHESTRATOR=local,
# LOGAN_LLM_PROVIDER=mock), which calls AnalyzeCasePipeline in-process:
scripts\local.ps1                     # Windows: bootstrap + run API and web (loads .env)
```

Note: the Makefile `worker` target runs `python -m logan_workers.workflows.analyze_case_workflow`, which has **no** `__main__` — prefer `python -m logan_workers.temporal_worker`.

## Test, lint, typecheck

```bash
python -m pytest tests/workers -q                    # this app's unit + e2e tests (no services)
python -m pytest tests/workers/test_pipeline.py -q   # single file
python -m pytest -q                                  # full backend suite (~2 min)
ruff check apps tests scripts                        # lint, line length 100
python -m compileall apps/api apps/workers           # the Python check `make lint` runs

# Benchmark quality gate (deterministic; non-zero exit = quality blocker):
python -m logan_workers.evaluation.run \
  --benchmark benchmarks/logan/checkout_incident \
  --out .logan/evaluation/report.json \
  --markdown .logan/evaluation/report.md            # or: make evaluate

# Synthetic scale benchmark:
python -m logan_workers.evaluation.scale --profile quick \
  --out .logan/evaluation/scale-quick.json          # or: make scale-benchmark
```

## Key concepts

- **Case / analysis run** — a case is an incident; an analysis run is one execution of the pipeline over uploaded logs. `case_id` + `analysis_run_id` thread through everything.
- **Golden signal** — each template/line is classified as one of `error`, `availability`, `latency`, `saturation`, `traffic`, `information`, `unknown`. `OFFENDING_SIGNALS` = the first five (they drive causal node selection and exports).
- **Template (Drain clustering)** — high-cardinality tokens are masked to `<*>` so many raw lines collapse into one `LogTemplate`; `template_id`/`template_text` are stamped back onto each `NormalizedLogLine`.
- **Representative sample** — a small, deterministic, redacted subset of lines per template. This is the **only** log content ever sent to the model.
- **Annotation** — the model's (or mock's) classification of a template: `golden_signal`, `fault_categories`, `entities`, `severity_score`, `confidence`, `rationale` — then broadcast to every line sharing that template.
- **Causal graph** — directed candidate-cause edges between offending templates, scored by temporal precedence + lagged correlation + lift + PGEM + Granger; nodes ranked (PageRank + earliness + severity) into `RootCauseCandidates`. Everything is *candidate / needs_validation*, never definitive.
- **Causal summary** — a cautious internal RCA plus a customer-safe update, built strictly from a redacted evidence packet; must cite `evidence_refs` and use hedging language.
- **EvidenceRef** — a stable pointer (case/run/template/log id + file_path + line_number + timestamp) tracing any claim back to a source line.
- **Window aggregate** — line counts bucketed into fixed time windows keyed by template/service/golden_signal/fault_category.
- **Redaction: mask vs hash** — secrets and PII replaced before model input; `hash` mode keeps a keyed HMAC token so identical values stay correlatable.
- **Orchestrator (local vs temporal)** — whether the pipeline runs in-process in the API or as a Temporal activity.

## Where to start reading

1. [CLAUDE.md](../../CLAUDE.md) — the "Architecture crib" lists the 10 steps and hard rules (fastest orientation).
2. `apps/workers/logan_workers/pipeline.py` — the whole orchestration and event model in one file.
3. `apps/workers/logan_workers/models.py` — the domain vocabulary every step passes around.
4. `apps/workers/logan_workers/activities/ingestion.py`, then `preprocessing.py`, `templating.py`, `sampling.py` — the deterministic front half (ingest → redact → template → sample).
5. `apps/workers/logan_workers/activities/inference.py` — the annotation model call + `MockAIPlatformAnnotationGateway` (the model seam).
6. `apps/workers/logan_workers/algorithms/redactors.py` and `representative_sampling.py` — the two privacy/quality guarantees.
7. `apps/workers/logan_workers/activities/causal.py`, then skim `algorithms/causal_series.py`, `causal_pgem.py`, `causal_granger.py`, `pagerank.py` for the scoring internals.
8. `apps/workers/logan_workers/activities/summary.py` — evidence-packet hardening + LLM-vs-fallback summary.
9. `apps/workers/logan_workers/workflows/analyze_case_workflow.py` + `temporal_client.py` + `activities/analysis.py` — dispatch under Temporal.
10. `tests/workers/test_pipeline.py` — the end-to-end contract and redaction/safety assertions.
11. `apps/workers/logan_workers/evaluation/evaluator.py` + `benchmarks/logan/checkout_incident/{manifest,labels}.json` — how quality is measured and gated.

## Common tasks

**Add a pipeline step.** Create an activity module under `activities/` (delegate heavy logic to a new `algorithms/` module); add a `run_step(...)` call in `pipeline.py` `_run_core` in the correct position returning count-only metadata; thread any output into `AnalysisResult` (`models.py`) if it must persist; register the step name in `PIPELINE_STEP_NAMES` (`apps/api/app/observability.py`) and `PIPELINE_STEPS` (`scripts/full_stack_smoke.py`); update `expected_steps` in `tests/workers/test_pipeline.py`; re-run `make evaluate`.

**Change how templates are mined.** Edit `algorithms/drain_adapter.py` (`StableDrainAdapter.to_template` regex masks or the `Drain3Adapter` config in `DrainConfig`). Keep `template_key`/`template_id` deterministic. Run `tests/workers/test_drain_adapter.py` and the benchmark (label patterns match templates by regex in `labels.json`).

**Tune causal edge / root-cause scoring.** Edit `activities/causal.py` (confidence weights, the `0.35` cutoff, the method set, the `rank_score` formula) and/or `causal_granger.py` / `causal_pgem.py` / `pagerank.py`. Validate with `tests/workers/test_causal_algorithms.py` and check `useful_causal_edge_recall` / `root_cause_hit` in `make evaluate`.

**Adjust redaction / add a secret pattern.** Add a regex + `Redactor.sub()` call in `algorithms/redactors.py`; if it must also be scrubbed from the summary packet, update `_FORBIDDEN_PACKET_KEYS` / secret regexes in `activities/summary.py` and the report scanners in `evaluation/reporting.py`. Assert via `tests/workers/test_pipeline.py::test_redaction_happens_before_model_input`.

**Change the mock model or a prompt.** Edit `MockAIPlatformAnnotationGateway` rules in `activities/inference.py` (annotation) / its `_summarize` path (summary), and/or the markdown in `prompts/annotation_prompt.md` / `prompts/causal_summary_prompt.md` (bump `PROMPT_VERSION` if the contract changes). Prompts are read at runtime with an inline fallback string.

**Wire a real production model gateway.** Implement an object with `async responses(**kwargs)` (see `apps/api/app/services/aiplatform_model_gateway.py`). The API injects it via `create_app(model_gateway=...)` and passes it to `AnalyzeCasePipeline.run(gateway=...)` on the local path. To use it under Temporal you must also thread a gateway into `activities/analysis.py` — it currently defaults to the mock (see gotchas below).

## Conventions & gotchas

- **The pipeline is really 11 `run_step` calls.** The 10 named steps — `ingest_paths`, `merge_entries`, `preprocess_redact`, `drain_templating`, `representative_sampling`, `ai_platform_annotation`, `broadcast_annotations`, `temporal_aggregation`, `causal_graph`, `causal_summary` — then `export_artifacts`. Only two touch the model gateway (`ai_platform_annotation`, `causal_summary`); the rest are pure algorithms.
- **Determinism is a hard requirement.** IDs come from `uuid5(NAMESPACE_URL, ...)` and `sha256`, the mock gateway is rule-based, and sorts are stable — so benchmark output is reproducible and CI-gateable. Preserve this when editing.
- **Count-only metadata rule.** Step events, progress, metric labels, and reports must never contain raw log text, prompts, file paths, credentials, or tokens. `reporting.ensure_report_text_is_safe()` and `summary._assert_summary_packet_safe()` actively enforce this and will raise. See CONTRIBUTING's "Redaction red lines".
- **The Temporal activity does not wire the real gateway.** `activities/analysis.py` calls `AnalyzeCasePipeline().run()` **without** a gateway, so it defaults to `MockAIPlatformAnnotationGateway`. The real AI Platform gateway is only injected on the local/in-process API path. Treat this as an intentional-scaffold gotcha to verify before relying on Temporal for production inference.
- **`temporalio` and `drain3` are optional imports.** Both are guarded by `try`/`except` with shims/fallbacks (`_WorkflowShim`/`_ActivityShim` in `workflows/`; `StableDrainAdapter` fallback in `drain_adapter.py`). Code must keep importing and running without them.
- **`causal_summary` degrades gracefully.** No gateway or schema-invalid model output → a deterministic fallback summary (`details.source = 'fallback'`, reason recorded). Tests assert both the `llm` and `fallback` branches.
- **`run_drain_templating` passes `config=drain_config` as a dict**, relying on `build_drain_adapter` accepting a mapping; engine selection (`drain3` default vs `stable`) lives in `DrainConfig`.
- **Adding a `LOGAN_*` setting or a pipeline step is a cross-repo change** (config.py, `.env.full.example`, README, docker-compose, k8s configmaps for settings; `PIPELINE_STEP_NAMES` + `PIPELINE_STEPS` + benchmark re-run for steps). Manifest/metric/smoke tests assert the sync — see CONTRIBUTING's "Conventions That Will Bite You".