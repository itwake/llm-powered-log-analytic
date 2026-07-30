# Reliability and explainability

LogAn separates deterministic log processing from optional model enrichment. The system is
designed to preserve evidence identity, minimize model input, validate model output, and present
causal results as candidates that require operator confirmation.

## Deterministic foundation

The following steps do not call a model:

- file and archive ingestion
- multiline merging
- parsing and redaction
- template extraction
- representative sampling
- annotation broadcasting
- time-window aggregation
- causal association scoring and candidate ranking

The same input files and run context produce stable templates and deterministic causal scoring.
Identifiers scoped to a run remain consistent inside its stored result.

## Model boundary

AI Platform is used only when `LOGAN_LLM_PROVIDER=ai_platform`:

1. Template annotation classifies bounded redacted samples.
2. Causal-summary generation turns a bounded evidence packet into cautious prose.
3. Analysis chat answers from the completed redacted result.

Raw uploaded files are not sent as model input. Template annotation is limited to 64 templates,
three samples per template, and 1,200 characters per sample. Chat receives a compact summary,
selected annotated rows, and up to five evidence references.

`LOGAN_LLM_PROVIDER=none` performs no model calls. It skips annotation, uses the structured summary,
and does not expose analysis chat.

## Redaction boundary

Uploaded files remain unchanged in the protected local data directory. During analysis, sensitive
patterns are masked before template extraction, representative sampling, report display, or model
input.

The redactor covers common secret assignments, URL query secrets, JWTs, bearer tokens, tenant and
customer identifiers, email addresses, IP addresses, UUIDs, and card-like numbers.

Redaction is rule based. It reduces exposure but cannot guarantee detection of every
application-specific secret format. Access to the upload directory must therefore remain
restricted.

## Output validation

Template annotations are validated with the `TemplateAnnotationResult` schema. A response that
does not satisfy the expected classification fields becomes an `unknown` annotation with zero
confidence.

Generated causal summaries are accepted only when:

- required narrative, claims, next actions, uncertainty, and confidence fields validate;
- every claim cites an evidence id present in the supplied packet;
- confidence values remain between zero and one.

If summary generation or validation fails, LogAn renders a structured summary from the evidence
packet. Annotation transport failures fail the run instead of silently creating classifications.

## Evidence-first results

Normalized lines retain their file, line, timestamp, and run identity. Raw entries and ingested
lines carry SHA-256 hashes while they pass through preprocessing, then are released instead of
being duplicated in the final result. Templates, samples, causal nodes, summary claims, and next
actions carry or derive from the durable normalized identities.

The report views expose this chain:

```text
summary or causal candidate
  -> evidence reference
  -> normalized redacted log
  -> uploaded file and line number
```

Evidence references explain where a claim came from; they do not by themselves prove that the
claim is correct.

## Causal interpretation

The causal graph uses temporal association rather than a model-generated graph. Candidate edges
combine:

- ordering of source and target events;
- the proportion of target events supported by a preceding source event;
- observed lag;
- shared service or entity context;
- source severity.

Every edge is marked `candidate_cause` and `needs_validation`. Operators should confirm candidates
with metrics, traces, deployment history, dependency health, and domain knowledge.

## Calibrated language

Summary claims are required to use cautious terms such as `candidate`, `likely`,
`evidence suggests`, or `needs validation`. Claims without that framing are automatically
prefixed as candidate findings.

The output includes explicit uncertainty, a confidence value, evidence references, and suggested
validation actions. A customer update is separated from the internal diagnostic narrative.

## Access and storage controls

- Production authentication is SSO-only; development can use the local default user.
- Each case is visible only to its creator.
- Case, upload, run, report, and chat routes enforce ownership.
- Browser session tokens are random; only their SHA-256 hashes are stored.
- SQLite foreign-key checks are enabled.
- Errors are sanitized before being persisted or returned as run failures.
- AI Platform credentials remain process configuration and are not stored in analysis results.

## Operational limits

The current deployment shape intentionally favors a single-instance system:

- Analysis tasks run inside one API process and are not resumed after an abrupt process failure.
- SQLite and local file storage require the API database and upload directory to remain together.
- An API instance does not share in-memory task state with another instance.
- Model annotation availability affects enriched labels and therefore the causal graph.
- Rule-based parsing, templating, redaction, and temporal association have domain-specific limits.
- The automated tests verify contracts and deterministic fixtures, not production incident
  diagnosis accuracy across every log format.

These limits should be considered when interpreting results or planning a larger deployment.
