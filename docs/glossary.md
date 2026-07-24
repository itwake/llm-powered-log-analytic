# Glossary

- **Case** — incident workspace containing access rules, uploaded files, and analysis runs.
- **Analysis run** — one immutable execution of the pipeline for selected case files.
- **Raw file** — uploaded file metadata plus its internal local file URI.
- **Normalized log line** — parsed, redacted line with stable file and line references.
- **Template** — variable-masked message shape produced by `StableDrainAdapter`.
- **Representative sample** — selected redacted example used for template annotation.
- **Golden signal** — latency, traffic, error, availability, saturation, information, or unknown.
- **Offending signal** — a signal eligible for causal candidate analysis.
- **Time-window aggregate** — count grouped by window and signal/service; rendered in the UI’s
  “Temporal View.”
- **Temporal precedence** — evidence that one template tends to occur before another; unrelated to
  workflow orchestration.
- **Causal edge** — directed candidate relationship with evidence, confidence, and validation
  state.
- **Root-cause candidate** — ranked graph node requiring operator validation.
- **Evidence reference** — stable case/run/template/log/file/line/timestamp pointer.
- **Step manifest** — safe local JSON artifact describing a completed pipeline step.
- **Ephemeral store** — isolated in-memory SQLite instance of `SQLAlchemyStore` used by tests.
