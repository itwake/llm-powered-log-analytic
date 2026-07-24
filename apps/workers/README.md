# LogAn analysis engine

`logan_workers` is an importable Python analysis package. The historical directory name remains
for package compatibility, but there is no separate worker process: the API calls
`AnalyzeCasePipeline` directly.

The pipeline has one deterministic path:

1. ingest files and archives
2. merge multiline records
3. normalize and redact
4. cluster templates with `StableDrainAdapter`
5. select representative samples
6. annotate redacted templates through the model gateway
7. broadcast labels
8. aggregate time windows
9. rank candidate causal relationships
10. generate a cautious summary and exports

Only representative redacted content is sent to the model. The causal graph combines time
precedence, lift, lagged correlation, PGEM-style, Granger-style, and PageRank-style evidence;
these remain candidates requiring validation.

## Development

```bash
python -m pip install -e .
python -m pytest tests/workers
python -m logan_workers.evaluation.run \
  --benchmark benchmarks/logan/checkout_incident \
  --out .logan/evaluation/report.json \
  --markdown .logan/evaluation/report.md
```

Important modules:

- `pipeline.py` — orchestration and progress events
- `models.py` — shared Pydantic domain models
- `ports.py` — model-gateway boundary
- `activities/` — pure analysis stages
- `algorithms/` — parsing, redaction, stable clustering, and causal scoring
- `evaluation/` — deterministic quality and scale benchmarks
