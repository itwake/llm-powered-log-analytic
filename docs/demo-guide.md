# Demo Guide

A scripted 10-minute walkthrough that shows every core capability using the bundled
deterministic incident. Works fully offline with the mock LLM provider.

## The story in the data

`scripts/generate_demo_logs.py` writes a ~2,600-line, one-hour incident to `demo/logs/`:

> At 10:08 auth-service's database connection pool starts running hot; at 10:10 it is
> exhausted. From 10:11 payment-service times out calling auth-service, and from 10:12 the
> gateway returns 500 on POST /checkout. Everything recovers at 10:33. Healthy traffic runs
> before and after, a batch job throws unrelated disk errors mid-incident (a red herring), and
> the set includes Java stack traces, emails/IPs/tokens/card numbers, and a gzip archive.

The expected result, end to end: **~2,600 raw lines collapse to ~8 offending templates
(≈99.7% review reduction)**, the Temporal View shows the incident wave, and the Causal Graph's
highest-confidence edges reproduce the chain
`auth pool exhausted → payment timeout → gateway 500`, with the batch-job noise staying
peripheral.

## Setup (one command each)

Start the stack (see README Quick Start for alternatives):

```powershell
.\scripts\local.ps1        # Windows; or: make quickstart-up (Docker)
```

Generate the demo logs (deterministic; `demo/logs/` is also committed, so this is optional):

```powershell
.venv\Scripts\python.exe scripts\generate_demo_logs.py
```

Choose how to create the case:

- **Live on stage** (recommended): create the case in the UI and drag-and-drop the four files
  from `demo/logs/` — the upload flow is part of the show.
- **Pre-seeded**: `python scripts/seed_demo_case.py --logs-dir demo/logs` does everything and
  prints the five view URLs.

## Walkthrough with talking points

1. **Sign in** — click "Continue with SSO". Point out: the product is SSO-only; locally a mock
   IdP stands in, so the demo needs no credentials.
2. **Create the case** — title "Checkout API intermittent 500 errors", production environment,
   incident window 10:00–11:00. Point out: cases are the unit of collaboration and RBAC.
3. **Upload** — drag all four files in, including the `.log.gz`. Point out: gzip/zip/JSONL are
   unwrapped automatically; bytes land in object storage with hash evidence.
4. **Run analysis and watch the progress panel** — the 10 pipeline steps stream live. Talking
   point while it runs: *representative lines only* — the model never sees raw logs, only a
   handful of redacted representatives per template, and results are broadcast back.
5. **Data Summary** — the headline number: ~2,600 lines reduced to ~8 offending templates
   (≈99.7% less to read). Signal breakdown: saturation (auth pool), availability (timeouts),
   error (gateway 500s, batch disk errors), traffic (retries).
6. **Temporal View** — the incident wave: information-level traffic throughout, error/
   availability/saturation stacking up between 10:10 and 10:33. Click a peak window — it
   deep-links into Tabular Logs filtered to that window.
7. **Tabular Logs** — three things to show:
   - filter `q=user_email`: redaction in action (`<EMAIL>`, `<IP>`, `<UUID>`, tokens, card
     numbers masked before anything reached a model);
   - filter `q=SocketTimeoutException`: the merged multi-line Java stack trace as one entry;
   - every row keeps file/line evidence back to the raw upload.
8. **Causal Graph** — the money shot. The highest-confidence directed edges are
   `auth pool exhausted → payment timeout` and `payment timeout → gateway 500`. Click an edge:
   temporal precedence, lift, PGEM-style and Granger-style evidence with `needs_validation`
   flags. Point out the batch-job disk errors sitting off the main chain — correlation noise
   the ranking keeps peripheral. Language is deliberately *candidate*, never "proven root
   cause".
9. **Causal Summary** — cautious narrative naming auth-service pool saturation as the leading
   root-cause candidate, with next actions and clickable evidence refs. With AI Platform
   credentials configured this is model-written; offline it falls back to a deterministic
   evidence-based rendering.
10. **Exports** (optional) — Markdown/HTML/JSON reports for ticket attachments.

## Resetting between rehearsals

```powershell
# stop the API, then:
Remove-Item -Recurse -Force .logan    # wipes SQLite metadata and uploaded objects
```

Restart and re-seed. Each seeding run creates a fresh case, so simply re-running
`seed_demo_case.py` also works if you don't mind old cases in the list.

## Notes

- The mock provider is deterministic: the same logs always produce the same templates,
  annotations, and graph — safe for live demos.
- The chat panel gives canned responses under the mock provider; demo it only when AI Platform
  credentials are configured.
- Everything above also works against the Docker quickstart stack and the standalone image.
