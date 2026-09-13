# Analysis pipeline

LogAn executes one ordered analysis pipeline inside the API process. A run accepts completed
upload identifiers, resolves them to local files, records progress after every step, and stores
one final `AnalysisResult`.

## Run lifecycle

A case moves through these states:

```text
created -> uploading -> analyzing -> completed
                                  \-> failed
                                  \-> cancelled
```

An analysis run moves through:

```text
queued -> processing -> completed
                    \-> failed
                    \-> cancelled
```

Starting a run creates an asynchronous task in the API process. Cancelling the run cancels that
task and records the terminal state. A graceful API shutdown also cancels active tasks.
Synchronous file and CPU work runs outside the API event loop so case and progress requests remain
responsive while large inputs are analyzed.

After `causal_summary` completes, the run enters `finalizing` while the report result is encoded
and committed. The run does not become `completed`, and report endpoints do not expose a result,
until that commit succeeds. A finalization failure moves both the run and case to `failed`.

## Inputs

Supported file types are:

- `.log`
- `.txt`
- `.json`
- `.jsonl`
- `.zip`
- `.gz`
- `.tar`
- `.tgz` and `.tar.gz`

Each uploaded file and its expanded archive content are limited to 300 MiB by default.
`LOGAN_MAX_UPLOAD_BYTES` configures both limits in bytes. Archive members are read as log inputs;
files are not extracted into user-controlled filesystem paths.

## Processing steps

### 1. Ingest paths — `ingest_paths`

`ingest_paths` reads plain files and archives. Every physical line receives a file id, file path,
line number, SHA-256 hash, and ingestion order. These fields establish the evidence identity used
by later steps.

### 2. Merge entries — `merge_entries`

`merge_entries` joins recognized stack-trace and exception continuation lines into one logical
entry. The entry retains all original line numbers and raw-line identifiers. Ordinary lines
without a timestamp are kept separate unless they match a continuation pattern.

### 3. Parse and redact — `preprocess_redact`

`preprocess_redact` parses timestamps, log levels, services, and common structured fields. An
entry without a timestamp may inherit the previous timestamp.

Before template generation or model input, the redactor masks:

- URL query secrets
- JWTs and bearer tokens
- password, secret, token, and API-key assignments
- tenant and customer identifiers
- email addresses
- IPv4 and IPv6 addresses
- UUIDs
- card-like numbers

The normalized line stores the redacted message used by reports and downstream analysis.

### 4. Extract templates — `template_extraction`

`TemplateExtractor` replaces timestamps, identifiers, key-value values, numbers, and path-like
values with `<*>`. Lines with the same resulting message shape are grouped into one template.
Each line receives a template id, while the template records its occurrence count, time range,
services, files, and a representative log id.

### 5. Select representative samples — `representative_sampling`

The pipeline selects up to three redacted samples per template. Samples retain evidence
references and provide bounded input for template annotation.

### 6. Annotate templates — `ai_platform_annotation`

When the run was started with an AI provider, at most 64 templates are sent to that provider
using the run's model and thinking level. Each sample message is limited to 1,200 characters.
The step name is historical; it applies to AI Platform and GitHub Copilot alike. The validated
response supplies:

- one golden signal
- fault categories
- structured entities
- severity and confidence
- a short rationale

Without a provider, this step is marked `skipped`; the pipeline does not create synthetic
annotations.

### 7. Broadcast annotations — `broadcast_annotations`

`broadcast_annotations` copies each template annotation to all normalized lines in that template.
Without an annotation, the line remains `unknown` with no model-derived categories or entities.

### 8. Aggregate time windows — `temporal_aggregation`

`build_time_window_aggregates` counts timestamped lines by template, service, golden signal, and
fault category. The default window is selected from the incident duration:

| Duration | Window |
| --- | --- |
| Up to 30 minutes | 10 seconds |
| Up to 3 hours | 60 seconds |
| Up to 24 hours | 5 minutes |
| Longer | 15 minutes |

### 9. Build causal candidates — `causal_graph`

Only templates labeled with an offending signal participate:

```text
error, availability, latency, saturation, traffic
```

The algorithm proposes directed `temporal_association` edges using event order, target support,
lag, shared service or entity context, and source severity. It ranks early templates with
supported downstream associations as root-cause candidates.

Every edge is a candidate with `needs_validation=true`. The score is an investigation aid, not
proof of causation.

### 10. Render the causal summary — `causal_summary`

The summary receives a bounded, redacted evidence packet containing selected log lines, supported
edges, candidates, and case context.

With a provider, model output must satisfy the summary schema and cite evidence ids from the
packet. Invalid output falls back to a structured, cautious summary. Without a provider, the
structured summary is used directly.

## LLM modes

| Capability | No provider | AI provider selected |
| --- | --- | --- |
| Ingestion, parsing, redaction, templates | Yes | Yes |
| Representative samples | Yes | Yes |
| Template classification | Skipped | Yes |
| Temporal aggregation | Yes | Yes |
| Causal candidate scoring | Runs on available offending labels | Runs on model annotations |
| Causal summary | Structured evidence summary | Generated text with structured fallback |
| Analysis chat | Yes, with any connected provider, after the run completes | Yes, after the run completes |

Because a run without a provider does not invent template classifications, attention-only
summaries and causal graphs can be empty. Use the `all` scope in Data Summary to review extracted
templates.

## Persistence and reports

Progress is stored on the analysis-run row while the task runs. On completion, one validated
logical `AnalysisResult` is stored as a versioned manifest in `analysis_runs.result_json` with
checksummed, compressed artifacts in local object storage. Analysis-only raw-line and raw-entry
collections, duplicate message forms, and per-line template copies are omitted from the persisted
artifacts. The original uploads remain in protected local storage, while report rows retain the
redacted message and evidence identity required by the UI.

Data Summary, Temporal View, Tabular Logs, Causal Graph, Causal Summary, and analysis chat all read
the same logical validated result. Physically, completion writes independently compressed summary,
temporal, graph, and causal-summary artifacts plus 10,000-row log chunks, then commits a compact
manifest to SQLite. Each report endpoint validates only its section. The default Tabular Logs
request reads only the chunks intersecting the requested page; filtered searches scan chunks
sequentially with bounded memory. There is no second analytical schema to reconcile.

The manifest stores aggregate log-facet counts used by the initial Tabular Logs view. Filtered or
searched views recompute facets from matching rows while scanning the chunks.

## Traceability

During ingestion, raw physical lines and merged entries carry SHA-256 hashes. Those raw
intermediates are released after preprocessing rather than copied into the final report result.
An `EvidenceRef` carries the durable report identity:

- case id
- analysis run id
- template id when available
- log id
- file path
- line number
- timestamp when available

Report evidence links use these fields to return to the corresponding redacted log row.
