# User guide

LogAn organizes an incident investigation as a case. A case contains incident context, uploaded
files, and one or more analysis runs.

## Sign in

Open the web application and continue to LogAn. Development signs in as the local default user
when SSO is not configured. With SSO enabled, the first successful callback creates the local user
profile automatically. A session cookie keeps subsequent API requests authenticated.

Use the sign-out button at the bottom of the sidebar to revoke the current session.

## Browse cases

The Cases page shows case totals and current states. Filter the list by status or product.

Case states are:

- `created`
- `uploading`
- `analyzing`
- `completed`
- `failed`
- `cancelled`

Only cases created by the signed-in user are visible.

## Create a case

Choose **New Case** and enter a title. The remaining fields are optional:

- issue description
- product
- service
- environment
- incident start and end

There are two submission paths:

- **Create case** saves the workspace without starting analysis.
- **Create, upload, and analyze files** creates the case, uploads the selected files, and starts
  the first run.

Accepted inputs are log, text, JSON, JSONL, zip, gzip, tar, and tgz files. Each file and its
expanded archive content must fit within the server upload limit, which defaults to 300 MiB.
Files of another type are listed as skipped, choosing files again adds to the selection, and a
selected file can be removed from its chip.

## Use the case workspace

The workspace displays:

- case details and edit controls;
- upload and analysis controls;
- analysis progress;
- run history;
- selected evidence;
- analysis chat for completed runs, with provider, model, and thinking selection.

Use **Edit case** to change incident context. Deleting a case marks it deleted and removes it from
normal case access. Uploaded files are not automatically erased and should be managed with the
local data directory as part of operational retention.

## Start another run

Select one or more files under **Analyze evidence**, pick the AI provider, model, and thinking
level (or **No AI** for the deterministic pipeline), then choose **Upload and analyze files**.
Every action creates a separate run over the newly uploaded file ids. The run inspector and the
report header show which provider, model, and thinking level produced a run.

Run states are:

- `queued`
- `processing`
- `completed`
- `failed`
- `cancelled`

The progress panel shows the current pipeline step and available counts. A processing run can be
terminated from the progress panel or run history. After the ten analysis steps finish,
**preparing reports** means the result is still being finalized. Open report views after the run
status changes to `completed`.

When a run asked for an AI provider but the model calls failed, the progress panel, the run
details, and the report header say so: those templates keep their rule-based classification and
the summary is built from structured evidence. Confirmations and errors for uploads, runs, and
case edits appear as a toast at the bottom of the window.

Select a run in **Analysis Runs** to inspect its status. Report links are tied to a specific run id,
so historical results remain separate. The report links in the workspace point at the newest
completed run and stay disabled, with an explanation, until a run has completed.

## Data Summary

Data Summary groups repeated messages into templates and shows representative content, occurrence
counts, time ranges, services, classification, severity, and confidence.

Each template is shown as one real line from its group with the values that vary between lines
highlighted. Structured lines show their `msg` text first and the remaining fields below it. When
no sample line is available, each varying value appears as an ellipsis.

The default **Attention** scope shows templates annotated with an offending golden signal. Choose
**All** to inspect every extracted template. In `none` mode, use **All** because no AI annotations
are created.

The metrics compare visible templates with raw line count and estimate the reduction in items that
need manual review.

## Temporal View

Temporal View displays aligned log counts as a stacked time chart. Use the legend and zoom controls
to compare series, or select a bar to open the matching log window. Group the series by:

- golden signal
- service
- fault category
- template

Series grouped by template are labelled with the template's message text. Lines without a parsed
or inferred timestamp do not contribute to time windows.

## Tabular Logs

Tabular Logs displays normalized redacted messages. Search across message text, template text, and
annotated entity values, or filter by exact service name.

The time column shows UTC with millisecond precision, the zone and precision of the log files.
Within each message, the values that vary across the lines of its template are highlighted. Each
row includes its file path and line numbers. Multiline entries can contain more than one physical
line number. Evidence links from other views open the corresponding log context.

## Causal Graph

Causal Graph draws templates and their strongest supported directed associations. Node size
represents causal rank, red rings identify root-cause candidates, and dashed edges require
validation. Nodes and the edge table are labelled with the message text of a representative line.
Select a node or edge for details; the table below the graph contains the complete edge list with
confidence, lag, and support. Use **Min confidence** and **Max nodes** above the graph to widen or
narrow it; the legend shows the colour of each golden signal. Candidate cards, the selected node,
and the endpoints in the edge table open the matching logs.

Treat the graph as a prioritized validation plan. It reports temporal associations and never
declares a proven root cause.

An empty graph means that the run did not contain enough annotated offending events or supported
associations.

## Causal Summary

Causal Summary contains:

- an internal diagnostic narrative;
- a customer-safe update;
- confidence and uncertainty;
- evidence references;
- candidate claims;
- next validation actions.

Select an evidence reference to inspect its file and line details or open it in Tabular Logs.

Without an AI provider, or when the provider is unavailable during summary generation, the page shows a structured
evidence summary instead of generated prose.

## Analysis chat

Analysis chat appears in the case workspace once the case has at least one run and answers about
the most recent completed run. Choose the AI provider, model, and thinking level above the
composer; the choice defaults to the provider, model, and thinking level the run was created
with. Runs created without AI can still be discussed with any connected provider.

Chat answers from the stored redacted analysis result. Responses stream into the workspace and can
include evidence references. Use those references to verify important statements in Tabular Logs.
Each answer is labelled with the provider, model, and thinking level that produced it.

Chat history is kept per case in the current browser tab until the tab closes, so opening a report
and coming back does not lose it; **Clear chat** discards it. It is not stored as part of the case.

## AI Providers

Open **AI Providers** in the sidebar to manage the providers available to your account. Providers
belong to you only; other users configure their own.

- **Add AI Platform**: name the provider and enter your iB2B username, password, and usercase.
  The gateway endpoints come from the deployment, so they are not asked for here.
- **Add GitHub Copilot**: name the provider and save it, then choose **Connect GitHub**. Enter the
  one-time code on the GitHub page that opens and confirm; the card shows the connected account.
- Edit the model list, the default model, and the default thinking level on each provider. Extra
  model ids can be typed into the list.
- **Test connection** sends a minimal request through the provider.

New runs pre-select the first provider that has usable credentials. Chat pre-selects the
provider, model, and thinking level of the run it answers about (or the first connected provider
when that run had none) until you choose another.

## Interpreting results

- `unknown` means no validated classification was available.
- Confidence is a ranking aid, not a probability that a root cause is proven.
- Missing timestamps reduce temporal and causal evidence.
- A small number of templates can represent many repeated log lines.
- Validate causal candidates with telemetry and operational context before using them in an RCA.
