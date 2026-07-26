# Glossary

- **Analysis result** — the validated output of one run, stored in
  `analysis_runs.result_json` and used by every report endpoint.
- **Analysis run** — one execution over selected completed uploads. Its lifecycle is
  `queued`, `processing`, then `completed`, `failed`, or `cancelled`.
- **Annotation** — AI Platform classification of one template into a golden signal, fault
  categories, entities, severity, confidence, and rationale.
- **Case** — an incident workspace containing context, uploads, and analysis runs. A case is owned
  by the user who created it.
- **Causal edge** — a directed candidate temporal association between two offending templates.
  Every edge requires validation.
- **Causal summary** — cautious incident narrative, evidence claims, uncertainty, customer update,
  and next validation actions derived from a bounded evidence packet.
- **Evidence reference** — pointer containing case, run, template, log, file, line, and optional
  timestamp identity.
- **Fault category** — annotation label describing a failure domain, such as dependency, resource,
  timeout, network, or application.
- **Golden signal** — one of `error`, `availability`, `latency`, `saturation`, `traffic`,
  `information`, or `unknown`.
- **Local object directory** — filesystem root configured by
  `LOGAN_LOCAL_OBJECT_STORE_DIR` for uploaded files.
- **Log entry** — one logical message after multiline continuations have been joined.
- **Model gateway** — the API boundary used for AI Platform annotation, summary generation, and
  chat.
- **Normalized log line** — parsed and redacted logical entry with stable evidence identity.
- **Offending signal** — `error`, `availability`, `latency`, `saturation`, or `traffic`; only these
  labels participate in causal candidate analysis.
- **Representative sample** — bounded redacted example selected from a template for annotation.
- **Root-cause candidate** — highly ranked early causal node with supported downstream
  associations; it is not a proven root cause.
- **Template** — message shape produced by replacing timestamps, ids, key-value values, numbers,
  and paths with `<*>`.
- **Temporal association** — candidate relationship scored from ordering, support, lag, shared
  context, and severity.
- **Time-window aggregate** — count grouped by time window, template, service, golden signal, and
  fault category.
