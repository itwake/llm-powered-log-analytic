# Life of a log line

1. The browser requests an upload slot.
2. FastAPI creates a raw-file row and returns an authenticated content URL.
3. The content route writes bytes to the local object directory.
4. Completion validates size and SHA-256.
5. Starting a run resolves completed file IDs to local paths.
6. The in-process pipeline ingests files and archives, preserving file and line references.
7. Multiline records are merged, timestamps parsed, and sensitive values redacted.
8. `StableDrainAdapter` groups messages into deterministic templates.
9. Representative redacted templates are annotated through the model gateway.
10. Labels are broadcast to matching lines and aggregated into time windows.
11. Candidate causal edges and root-cause rankings are calculated.
12. The cautious summary and exports are generated.
13. `SQLAlchemyStore` persists normalized report rows and safe step manifests.

The same identifiers connect summary cards, the time-window view, tabular logs, graph nodes,
evidence links, and exports. Causal language remains qualified because the graph ranks evidence
rather than proving causation.
