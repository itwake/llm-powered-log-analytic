# LogAn Tutorial

LogAn is a log analysis tool for incidents. You open a case for one incident, upload its logs, run
an analysis, and then move between structured logs, a timeline, causal candidates, and a summary to
validate what happened. AI is optional: without a provider the whole pipeline still runs, you only
lose model annotations, generated summaries, and chat.

The tutorial has two parts. Chapter 1 is a ten-minute Quick Start. Chapters 2 onward explain every
page, field, and setting.

> 📷 **Screenshot placeholder:** every place that needs a screenshot is marked with a block like
> this one. The heading of the block says what to capture. UI text in this document (buttons,
> field names) matches the application exactly.

---

## 1. Quick Start

Goal: start LogAn from nothing, connect one AI provider, complete a first analysis, and ask a
question about it.

### 1.1 Prerequisites

- Python 3.11 or newer and Node.js 22 or newer.
- One working AI account, either a GitHub Copilot subscription or an iB2B account for your
  company's AI Platform.
- No SSO is needed for local development; without SSO configured, LogAn signs you in as a built-in
  local user.

### 1.2 Start the application

On Windows one command creates the virtual environment, installs dependencies, copies `.env`,
applies database migrations, and starts both the API and the web app:

```bat
scripts\local.bat
```

On other platforms, start manually in two terminals:

```bash
cp .env.example .env
python -m venv .venv
python -m pip install -e ".[dev]"
npm ci
python -m alembic -c apps/api/alembic.ini upgrade head
```

```bash
python -m uvicorn app.main:app --reload --env-file .env --app-dir apps/api --host 127.0.0.1 --port 8000
```

```bash
npm run dev --workspace @logan/web
```

Open `http://localhost:3000`.

> 📷 **Screenshot placeholder:** the login page with the "Continue to LogAn" card and the
> **Continue** button.

### 1.3 Sign in

Choose **Continue**. In development mode this signs you in as the local user
`local@logan.invalid` and opens the Cases page.

### 1.4 Connect an AI provider

Choose **AI Providers** in the sidebar.

Using GitHub Copilot as the example:

1. Choose **Add GitHub Copilot**, keep the default Name or pick one you will recognise, and choose
   **Create provider**.
2. On the new card choose **Connect GitHub**. The dialog shows a one-time code; choose
   **Open GitHub**, enter the code on the GitHub page, and confirm.
3. Back in LogAn the dialog reports success and the card shows **Ready** and
   "GitHub account &lt;your login&gt;".
4. Choose **Test connection** and wait for the green message.

> 📷 **Screenshot placeholder:** the Connect GitHub Copilot dialog showing the one-time code and
> the countdown.

> 📷 **Screenshot placeholder:** the provider card after connecting, with the **Ready** badge and a
> successful Test connection message.

Connecting AI Platform is described in section 4.2; an administrator must set the gateway
addresses in `.env` first.

### 1.5 Create a case and analyze it

1. Choose **New Case** in the sidebar and fill in Title (required).
2. Drag log files into the upload area or choose **Choose files**. Accepted types are
   `.log .txt .json .jsonl .zip .gz .tar .tgz`.
3. Check the three dropdowns **AI provider / Model / Thinking**; the first ready provider is
   preselected.
4. Choose **Create, upload, and analyze files**.

> 📷 **Screenshot placeholder:** the New Case form with files selected and the three dropdowns
> showing a provider, a model, and a thinking level.

The page opens the case workspace. The **Analysis Progress** panel on the right walks through
Ingest, Merge, and so on to Summary, and the run status ends as `completed`.

### 1.6 Read the reports

Use the navigation at the top to switch between **Summary / Timeline / Logs / Graph / RCA**. Start
with RCA (Causal Summary), then follow the references under Evidence into Logs to check the
underlying lines.

> 📷 **Screenshot placeholder:** the Causal Summary page.

### 1.7 Ask a question

Return to **Workspace**. In the **Analysis Chat** card pick the provider, model, and thinking level
(they default to what the analysis used), then type a question or choose a quick prompt such as
"What is the most likely root cause?". References under the answer open the evidence.

> 📷 **Screenshot placeholder:** the Analysis Chat card with one question, one answer, and its
> Evidence references.

That is the end of the Quick Start. The rest of the document explains each setting in detail.

---

## 2. Installation and configuration

### 2.1 Three ways to run

| Method | Command | Notes |
| --- | --- | --- |
| Windows launcher | `scripts\local.bat` | Handles dependencies, `.env`, migrations, and startup. Accepts `-ApiOnly`, `-WebOnly`, and `-SkipInstall`. Refuses to start when port 3000 or 8000 is in use |
| Manual | see 1.2 | API on 8000, web app on 3000 |
| Docker | `docker compose up --build` | Reads the same `.env`; the database and uploads live in the `logan-data` volume |

The API applies pending database migrations before it starts; the Docker image does the same
before starting Uvicorn.

### 2.2 `.env` settings

Copy `.env.example` for the minimum setup or `.env.full.example` for every setting. The API reads
`.env` through `--env-file .env`; the web app reads only `NEXT_PUBLIC_API_BASE_URL`, at build time.

#### Runtime

| Setting | Default | Meaning |
| --- | --- | --- |
| `LOGAN_ENV` | `development` | `production` turns on secure cookies, requires complete SSO, and requires a secret of at least 32 characters |
| `LOGAN_SECRET_KEY` | `change-me` | Signs sessions. Must be unique in production |
| `LOGAN_DATABASE_PATH` | `.logan/logan.db` | SQLite file; the directory is created when missing |
| `LOGAN_LOCAL_OBJECT_STORE_DIR` | `.logan/object-store` | Root for uploads and analysis artifacts |
| `LOGAN_MAX_UPLOAD_BYTES` | `314572800` (300 MiB) | Limit per file, also applied to the expanded contents of an archive |
| `LOGAN_WEB_BASE_URL` | `http://localhost:3000` | Where the browser is sent after login; must be the address the browser really uses |
| `LOGAN_CORS_ALLOWED_ORIGINS` | `http://localhost:3000,http://127.0.0.1:3000` | Web origins allowed to call the API, comma separated |
| `LOGAN_LOG_LEVEL` | `INFO` | Process log level |

#### SSO

| Setting | Meaning |
| --- | --- |
| `LOGAN_SSO_AUTHORIZE_URL` | Empty keeps the development local user; once set, the next two settings are required as well |
| `LOGAN_SSO_TOKEN_URL` | OAuth token endpoint |
| `LOGAN_SSO_CLIENT_ID` | OAuth client id |
| `LOGAN_SSO_AUTHORIZE_SCOPE` / `LOGAN_SSO_TOKEN_SCOPE` | Default `openid profile email` |
| `LOGAN_SSO_TLS_VERIFY` | Default `true`; cannot be disabled in production |
| `LOGAN_SSO_TIMEOUT_SECONDS` | Default `15` |

The SSO callback is the API's `/api/auth/sso/callback` and must be registered with the SSO
application.

#### AI Platform (deployment-wide)

The AI Platform gateway addresses belong to the deployment; users enter only their own
credentials. **Until the first three settings are set, an AI Platform provider cannot be created**;
the Add dialog reports which settings are missing.

| Setting | Default | Meaning |
| --- | --- | --- |
| `LOGAN_AI_PLATFORM_CHAT_HOST` | empty | Origin of the completions gateway, for example `https://ai.example.com` |
| `LOGAN_AI_PLATFORM_CHAT_URI` | `/v1/api/v1/chat/completions` | Completions path |
| `LOGAN_AI_PLATFORM_IB2B_HOST` | empty | Origin of the iB2B token exchange |
| `LOGAN_AI_PLATFORM_IB2B_URI` | `/dsp/rest-sts/DSP_iB2B/iB2B_tokenTranslator_v2?_action=translate` | Token exchange path |
| `LOGAN_AI_PLATFORM_TRUST_TOKEN_HEADER` | `X-XXXX-E2E-Trust-Token` | Header that carries the JWT |
| `LOGAN_AI_PLATFORM_TRACKING_PREFIX` | `EFP` | Prefix of the request tracking id |
| `LOGAN_AI_PLATFORM_MAX_COMPLETION_TOKENS` | `4096` | Cap on one answer |
| `LOGAN_AI_PLATFORM_STORE_COMPLETIONS` | `false` | Whether the gateway may store conversations, with metadata attached |
| `LOGAN_AI_PLATFORM_TOKEN_TTL_SECONDS` | `30` | How long an exchanged JWT is reused |
| `LOGAN_AI_PLATFORM_TIMEOUT_SECONDS` | `120` | HTTP timeout |
| `LOGAN_AI_PLATFORM_CA_BUNDLE` | empty | Corporate CA bundle for an internal certificate chain |
| `LOGAN_AI_PLATFORM_TLS_VERIFY` | `true` | Cannot be disabled in production |
| `LOGAN_AI_PLATFORM_PROXY_URL` | empty | Explicit proxy |
| `LOGAN_AI_PLATFORM_TRUST_ENV` | `true` | Whether the process `HTTP(S)_PROXY` variables are honoured |

#### GitHub Copilot (deployment-wide transport)

| Setting | Default | Meaning |
| --- | --- | --- |
| `LOGAN_GITHUB_COPILOT_TIMEOUT_SECONDS` | `120` | Timeout for github.com and the Copilot API |
| `LOGAN_GITHUB_COPILOT_CA_BUNDLE` | empty | Corporate CA bundle |
| `LOGAN_GITHUB_COPILOT_TLS_VERIFY` | `true` | Cannot be disabled in production |
| `LOGAN_GITHUB_COPILOT_PROXY_URL` | empty | Explicit proxy |
| `LOGAN_GITHUB_COPILOT_TRUST_ENV` | `true` | Whether `HTTP(S)_PROXY` is honoured |

The API must reach `github.com` (device authorization), `api.github.com` (Copilot token exchange),
and `api.githubcopilot.com` or whichever Copilot address the token exchange reports.

#### Web

| Setting | Default | Meaning |
| --- | --- | --- |
| `NEXT_PUBLIC_API_BASE_URL` | `http://localhost:8000` | API address the browser calls directly; read at build time, so rebuild the web app after changing it |

### 2.3 Production requirements

- HTTPS everywhere: web app, API, SSO provider, and AI gateways.
- A unique `LOGAN_SECRET_KEY` of at least 32 characters.
- All three SSO settings.
- Every `*_TLS_VERIFY` left at `true`.
- `LOGAN_CORS_ALLOWED_ORIGINS` limited to the deployed web origin.
- Restricted access to the database file and the upload directory. Provider credentials (AI
  Platform passwords, GitHub tokens) are stored in the database as supplied, so the database file
  is the security boundary.
- One API process per instance, because analysis runs execute inside the process.

---

## 3. Signing in and navigating

### 3.1 Login page

| Element | Meaning |
| --- | --- |
| **Continue** | Opens the API login endpoint. Development mode creates a session for the local user; with SSO configured it redirects to the SSO login page |

After login the API sets an HTTP-only session cookie that is valid for seven days.

> 📷 **Screenshot placeholder:** the login page.

### 3.2 Sidebar

| Item | Destination |
| --- | --- |
| **New Case** | The new case form |
| **All Cases** | The case list with filters |
| **AI Providers** | Your own provider management page |
| **Cases** group | Shortcuts to the 30 most recent cases; the dot colour reflects the case state |
| Avatar area at the bottom | The signed-in user; the icon on the right is **Sign out** |

The arrow at the top collapses the sidebar to icons.

> 📷 **Screenshot placeholder:** the expanded sidebar.

### 3.3 All Cases

| Element | Meaning |
| --- | --- |
| **Status** filter | Created / Uploading / Analyzing / Completed / Failed / Cancelled |
| **Product** filter | Exact match on the case's Product field |
| Columns | Status, Product, Service, Incident start |

Only cases you created are listed.

---

## 4. AI Providers

Each user manages their own providers; nobody else can see or use them. A provider stores three
things: credentials, the models it offers, and the default model and thinking level.

> 📷 **Screenshot placeholder:** the empty AI Providers page with the **Add AI Platform** and
> **Add GitHub Copilot** buttons.

### 4.1 Page layout

| Element | Meaning |
| --- | --- |
| **Add AI Platform** | Opens the create dialog with AI Platform preselected |
| **Add GitHub Copilot** | Opens the create dialog with GitHub Copilot preselected |
| Blue notice | Shown only when the deployment lacks the AI Platform gateway settings; it names the missing `.env` settings |
| Provider cards | One per provider, see 4.5 |
| **How providers are used** | Explains how providers take part in analysis and chat |

### 4.2 Add an AI Platform provider

Choose **Add AI Platform**. The dialog fields:

| Field | Required | Meaning |
| --- | --- | --- |
| Provider type | yes | AI Platform / GitHub Copilot; cannot be changed after creation |
| **Name** | yes | Display name, unique per user, at most 80 characters |
| **Username** | yes | iB2B username |
| **Password** | yes | iB2B password. Before each request it is exchanged for a short-lived JWT, which is cached only in memory |
| **Usercase** | yes | iB2B usercase, also sent as the request's `user` field |
| **Models** | yes | See 4.4 |
| **Default model** | yes | See 4.4 |
| **Default thinking level** | yes | See 4.4 |

Username, Password, and Usercase must be given together; a partial set is rejected. When editing,
an empty Password keeps the stored one; the placeholder reads "Unchanged".

> 📷 **Screenshot placeholder:** the Add AI provider dialog with the AI Platform type and the
> three Credentials fields.

### 4.3 Add a GitHub Copilot provider and authorize it

1. Choose **Add GitHub Copilot**, enter a Name, adjust the rest as needed, and choose
   **Create provider**. The card shows **Not connected**.
2. On the card choose **Connect GitHub**.

The dialog flow:

| Phase | What is shown | What to do |
| --- | --- | --- |
| Contacting GitHub… | A device code is being requested from github.com | Wait a second or two |
| Code shown | A one-time `XXXX-XXXX` code, **Copy code**, **Open GitHub**, and a countdown "code valid for m:ss" | Choose **Open GitHub** (new tab), enter the code, confirm the authorization |
| Authorized | Green message "GitHub Copilot is connected as &lt;login&gt;" | Choose **Done** |
| Failed | Red message and **Try again** | See chapter 10 for common causes |

This is GitHub's official device flow using the Copilot plugin client id. The LogAn server stores
the GitHub token in the database; the browser only ever sees the one-time code. Enterprise-managed
accounts may first need to pass the company SSO in the GitHub tab.

On a connected provider the button reads **Reconnect GitHub**; use it when the token stops working.

> 📷 **Screenshot placeholder:** one screenshot for each of the three phases of the Connect
> GitHub Copilot dialog.

### 4.4 Models, default model, default thinking level

These three settings decide what the dropdowns offer and preselect when you start an analysis or
ask a question.

**Models**: the model ids this provider offers.
- A new provider starts with the catalog list for its type (see Appendix A).
- Type an id and press Enter to add a custom model; the cross on a chip removes it.
- **Reset to the catalog list (N models)** restores the catalog. An existing provider does not
  change when the catalog is updated; use this button to sync it.
- Ids may contain letters, digits, and `. _ : / -`, with at most 32 models per provider.

**Default model**: one of the Models, preselected for new analyses and chat. The catalog defaults
are `gpt-5.4` for AI Platform and `gpt-5.6-terra` for GitHub Copilot.

**Default thinking level**: Low / Medium / High / Extra high / Max, stored as
`low / medium / high / xhigh / max`. The default is High. AI Platform receives it as
`reasoning_effort`; Copilot receives it as `reasoning.effort`.

> 📷 **Screenshot placeholder:** the Models field with several chips and the default model
> highlighted, the Reset button, and the two default dropdowns.

### 4.5 Provider card

| Element | Meaning |
| --- | --- |
| Badges | The provider type; **Ready** means credentials are complete, **Not connected** means none are stored yet |
| Credentials | AI Platform shows "iB2B credentials for &lt;username&gt;"; Copilot shows "GitHub account &lt;login&gt;"; without credentials "None stored yet" |
| Default model | The default model and thinking level |
| Models | Every model as a chip; the default one is filled |
| **Connect GitHub / Reconnect GitHub** | Copilot only |
| **Test connection** | Sends one tiny request with the default model at Low thinking. Success shows a green message; failure shows a red message with the reason. Disabled until credentials are complete |
| **Edit** | Opens the edit dialog with the same fields as create; the type cannot change |
| **Delete** | Removes the provider and its credentials. Past analyses that used it are kept, only the link to the provider is dropped |

> 📷 **Screenshot placeholder:** one AI Platform card and one connected Copilot card.

### 4.6 Where providers are used

- **Starting an analysis**: the New Case form and the Analyze evidence card in the workspace both
  carry the provider / Model / Thinking dropdowns, with **No AI (deterministic pipeline)** to skip
  the model. An analysis with a provider uses it for template annotation and the causal summary.
- **Chat**: every question can pick again. The defaults are the provider, model, and thinking
  level the analysis used; otherwise the first ready provider.
- A provider that is not connected appears in the dropdown but cannot be selected.

---

## 5. Creating a case

Choose **New Case** in the sidebar.

> 📷 **Screenshot placeholder:** the whole New Case page.

### 5.1 Case details

| Field | Required | Meaning |
| --- | --- | --- |
| **Title** | yes | Case title |
| **Issue description** | no | What was observed; a redacted, bounded copy is part of the context sent to the model |
| **Product** | no | Product name; All Cases can filter by it |
| **Service** | no | Service name |
| **Environment** | no | For example prod or staging |
| **Incident start / Incident end** | no | The incident window, entered in the browser's local time zone and stored as UTC |

### 5.2 Upload area

| Element | Meaning |
| --- | --- |
| Drop zone / **Choose files** | Multiple files allowed. Accepts `.log .txt .json .jsonl .zip .gz .tar .tgz` |
| Selected file chips | Name and size; the × removes a file. Choosing files again adds to the selection, and files of an unsupported type are listed as skipped |
| Limits | Each file must contain at least one byte; the default maximum is 300 MiB, and the expanded contents of an archive count against the same limit |

While uploading, the page shows the prepare, upload, and verify progress of each file.

### 5.3 AI selection

| Dropdown | Meaning |
| --- | --- |
| **AI provider** | **No AI (deterministic pipeline)** or any ready provider |
| **Model** | The selected provider's model list |
| **Thinking** | Low / Medium / High / Extra high / Max |

When no provider exists at all, a hint with a link to the AI Providers page appears here.

### 5.4 The two submit buttons

| Button | Behaviour |
| --- | --- |
| **Create case** | Saves the case only; no upload, no analysis |
| **Create, upload, and analyze files** | Creates the case, uploads the selected files, and starts the first analysis with the selection above. Disabled until files are selected |

---

## 6. The case workspace

Open a case from the sidebar, or arrive here after creating one. The layout has a wide left column
and a narrow right column.

> 📷 **Screenshot placeholder:** the whole workspace.

### 6.1 Case analysis navigation

Appears once the case has at least one analysis and switches between
**Workspace / Summary / Timeline / Logs / Graph / RCA**. The report links point at the newest
completed analysis and stay disabled, with an explanation, until one has completed.

### 6.2 Incident Overview card

| Element | Meaning |
| --- | --- |
| Case key and status badges | The case state and the latest analysis state |
| Title, description, metadata chips | Product / Service / Environment / Incident start |
| **Open latest report** | Appears once an analysis has completed; opens the Summary of the newest completed one |
| **Edit case** | Expands the edit form |

### 6.3 Edit Case form

Same fields as 5.1. **Save case** saves; **Cancel** collapses the form; **Delete case** asks for
confirmation, after which the case is no longer visible. Uploaded files are not deleted
automatically.

### 6.4 Analysis Chat card

See chapter 9.

### 6.5 Analyze evidence card

Upload again and start another analysis. Each start is a separate run over the newly uploaded
files only.

| Element | Meaning |
| --- | --- |
| Upload area | As in 5.2 |
| Upload progress | One bar per file with the percentage and byte counts |
| AI selection | As in 5.3 |
| **Upload and analyze files** | Disabled until files are selected |
| Feedback | Confirmations and errors appear as a toast at the bottom of the window |

### 6.6 Analysis Progress (right column)

| Element | Meaning |
| --- | --- |
| Heading | "Run #N · step", for example "Annotating with AI" |
| AI notice | When the run asked for a provider but model calls failed, a warning says how many annotation calls failed and whether the summary fell back to structured evidence |
| Metrics | Files / Raw lines / Templates / Windows |
| Step list | Ingest, Merge, Redact, Template, Sample, Classify, Annotate, Broadcast, Temporal, Graph, Summary; each shows pending / processing / completed / failed / skipped |
| Started / Completed | Timestamps |
| **Open report** | Appears when the run has completed |
| **Terminate** | Stops a run that is still processing |

Without AI the Annotate step shows `skipped`.

> 📷 **Screenshot placeholder:** the progress panel while an analysis is running.

### 6.7 Selected evidence

After choosing an evidence reference in Chat or a report, this panel shows its Log id, Template,
Line, and Timestamp and offers a link into Logs.

### 6.8 Case and Run details

The Case card lists the state and all metadata. The Run card lists the number, state, current
step, start and end times, and an **AI model** line in the form "provider name · model · thinking";
without AI it reads "None (deterministic)", and an **AI not applied** or **AI partial** badge
appears when model calls failed. A failed run shows its sanitized error message.

### 6.9 Analysis Runs history

One entry per analysis. Selecting one switches which run the right column follows; **Summary**
opens that run's reports; a run in progress can be stopped with **Terminate**.

---

## 7. Analysis runs

### 7.1 The pipeline

Every analysis executes these steps in order:

1. `ingest_paths` reads the files and expands archives
2. `merge_entries` joins multiline log entries
3. `preprocess_redact` parses and redacts (passwords, tokens, keys, and similar are masked before templates and models see them)
4. `template_extraction` extracts log templates
5. `representative_sampling` keeps at most three representative lines per template
6. `heuristic_annotation` classifies by rules, so results exist even without a model
7. `ai_platform_annotation` annotates at most the 64 most frequent templates with the selected provider (the step keeps its historical name; Copilot runs through it as well)
8. `broadcast_annotations` copies template annotations to every line
9. `temporal_aggregation` aggregates by time window
10. `causal_graph` scores causal candidates
11. `causal_summary` writes the summary; with a provider it generates prose, and invalid model output falls back to a structured summary

`finalizing` then writes the artifacts. A model receives only bounded, redacted samples and
evidence packets, never the raw files.

### 7.2 States

Case states: `created` `uploading` `analyzing` `completed` `failed` `cancelled`.
Run states: `queued` `processing` `completed` `failed` `cancelled`.

When the API restarts, a run that was in progress is marked `failed` with an explanation rather
than staying in processing forever.

### 7.3 When a model call fails

One failed template annotation does not fail the analysis; that template keeps its rule-based
classification. A failed summary generation falls back to the structured summary. A misconfigured
provider therefore still produces a `completed` run, only the Annotate results and the RCA prose
are missing. Use **Test connection** on the provider card to find out why.

---

## 8. Report pages

The five report pages share a run version bar at the top:

| Element | Meaning |
| --- | --- |
| **Version** dropdown | Switches between the analyses of the same case |
| Completed | Completion time |
| Model | The provider, model, and thinking level of that analysis |

> 📷 **Screenshot placeholder:** the version bar at the top of a report page.

### 8.1 Summary (Data Summary)

| Element | Meaning |
| --- | --- |
| Metrics | Raw lines, Visible templates, Review reduction (how much less there is to read compared with the raw line count) |
| **Scope** | **Attention signals** shows only templates annotated with an offending signal (error, availability, latency, saturation, traffic); **All templates** shows everything. Use All for analyses without AI |
| List | Each template as one real line with the varying values highlighted (structured lines show their `msg` text first), occurrence count, time range, services, classification, severity, and confidence |

> 📷 **Screenshot placeholder:** the Summary page.

### 8.2 Timeline (Temporal View)

| Element | Meaning |
| --- | --- |
| **Group by** | Signal / Service / Fault category / Template |
| Stacked bars | Log counts per time window; the window size is chosen from the incident duration (10 seconds to 15 minutes) |
| Selecting a bar | Loads the logs of that window below the chart |

Lines without a timestamp do not take part in the timeline.

> 📷 **Screenshot placeholder:** the Timeline page with one window opened.

### 8.3 Logs (Tabular Logs)

| Element | Meaning |
| --- | --- |
| **Search** | Searches messages, template text, and annotated entity values; Enter runs the search |
| Table | Time in UTC with millisecond precision, redacted message with the values that vary across its template highlighted, file, line numbers (a multiline entry lists several), template, signal, categories |

Evidence references from other pages open this page filtered to the evidence's template, so
related lines are visible together.

> 📷 **Screenshot placeholder:** the Logs page.

### 8.4 Graph (Causal Graph)

| Element | Meaning |
| --- | --- |
| Graph | Nodes are templates, labelled with the message text of a representative line; larger nodes rank higher; red rings mark root-cause candidates; dashed edges still need validation |
| **Min confidence / Max nodes** | Hide weaker edges or limit the graph size |
| Legend | The colour of each golden signal present in the graph |
| Selecting a node or edge | Shows its details; a selected node offers **Open logs** |
| Edge table | Every association with confidence, lag, and the number of supporting windows; each endpoint opens the matching logs |
| **Logs** on a candidate card | Opens the logs around the candidate's representative line |

Edges are temporal associations, a suggested validation order rather than proof. An empty graph
means there were not enough offending events or supported associations.

> 📷 **Screenshot placeholder:** the Graph page.

### 8.5 RCA (Causal Summary)

| Section | Meaning |
| --- | --- |
| Internal narrative | Written for engineers |
| Customer-facing update | A safely worded external version |
| Confidence and uncertainties | |
| **Evidence** | References; select one to inspect it or jump into Logs |
| Candidate claims | Each with a reason, references, and confidence, all marked as needing validation |
| **Next actions** | Suggested validation steps with a priority and an owner role |

Without AI, or when the model output is invalid, the page shows a structured evidence summary
instead of generated prose.

> 📷 **Screenshot placeholder:** the RCA page.

---

## 9. Analysis Chat

Shown in the workspace once the case has at least one analysis; it answers about the most recent
`completed` analysis.

> 📷 **Screenshot placeholder:** the empty Chat card with the four quick prompts and the three
> dropdowns.

| Element | Meaning |
| --- | --- |
| Subtitle | "Answers about run #N" |
| Quick prompts | Summarize what changed and why it matters / What is the most likely root cause? / Show the strongest evidence / Draft a customer-safe update |
| **AI provider / Model / Thinking** | Can be changed before every question. Defaults to the analysis's own choice; for an analysis without AI, the first ready provider |
| Input | Enter sends, Shift+Enter inserts a line break |
| **Ask / Cancel** | Sends; a streaming answer can be cancelled |
| Label under the answer | "provider name · model · thinking", shown even when the answer failed |
| Evidence references | Selecting one shows its details in Selected evidence |

The model receives a compact analysis context: your question (at most 1,000 characters), the
causal summary (2,500 characters), up to five evidence references, and the five most severe
templates. Chat history is kept per case in this browser tab: it survives opening a report and
coming back, and is gone when the tab closes or after **Clear chat**.

---

## 10. Troubleshooting

**Add AI Platform reports that endpoints are not configured.**
An administrator sets `LOGAN_AI_PLATFORM_CHAT_HOST`, `LOGAN_AI_PLATFORM_IB2B_HOST`, and
`LOGAN_AI_PLATFORM_IB2B_URI` in `.env` and restarts the API.

**Test connection reports iB2B token exchange failed.**
The username, password, or usercase is wrong, or the API cannot reach the iB2B address. For an
internal certificate chain set `LOGAN_AI_PLATFORM_CA_BUNDLE`.

**The Connect GitHub code expired.**
The code is valid for about fifteen minutes; choose **Try again** for a new one. Enterprise
accounts should complete the company SSO in the GitHub tab before entering the code.

**Copilot answers 401 or asks you to reconnect GitHub.**
The GitHub authorization has expired; choose **Reconnect GitHub** on the card.

**Copilot reports that the model is not available or not supported.**
The model is not part of your subscription, or the catalog id differs from what Copilot expects.
Open **Edit** on the provider and correct the id or pick another default model.

**The analysis completed, but Annotate looks like it ran without AI and RCA has no prose.**
Model calls fall back inside the pipeline (see 7.3); the progress panel shows an AI notice with
the failed call count and the run details and report header show an **AI not applied** or
**AI partial** badge. Run **Test connection** first, then check the proxy and certificate settings
in `.env`.

**An upload returns 500 and the log says "No such file or directory".**
Older versions failed on Windows when a path exceeded 260 characters; the current version handles
it. If it still happens, move `LOGAN_LOCAL_OBJECT_STORE_DIR` to a shorter directory.

**The browser reports CORS or 401 errors.**
Open `http://localhost:3000` and keep `LOGAN_WEB_BASE_URL`, `LOGAN_CORS_ALLOWED_ORIGINS`, and
`NEXT_PUBLIC_API_BASE_URL` consistent with the real addresses.

**SSO returns to the wrong address.**
`LOGAN_WEB_BASE_URL` must be the web address the browser sees.

**An upload is rejected.**
Each file must contain at least one byte and defaults to a 300 MiB maximum; expanded archives count
against the same limit. Adjust `LOGAN_MAX_UPLOAD_BYTES`.

---

## Appendix A: catalog models

**AI Platform**: `gpt-5.4` (default), `gpt-5.6-luna`, `gpt-5.6-sol`, `gpt-5.6-terra`.

**GitHub Copilot** (the Copilot model picker; default `gpt-5.6-terra`):

| Display name | id |
| --- | --- |
| Sonnet 4 / Haiku 4.5 | `claude-sonnet-4` / `claude-haiku-4.5` |
| Fable 5 / Fable 5.1 | `claude-fable-5` / `claude-fable-5.1` |
| Opus 4.7 / 4.8 / 5 | `claude-opus-4.7` / `claude-opus-4.8` / `claude-opus-5` |
| Sonnet 5 | `claude-sonnet-5` |
| Gemini 3.7 Flash / 3.8 Flash | `gemini-3.7-flash` / `gemini-3.8-flash` |
| GPT-5.4 / GPT-5.4 mini / GPT-5 mini | `gpt-5.4` / `gpt-5.4-mini` / `gpt-5-mini` |
| GPT-5.6 Luna / Sol / Terra | `gpt-5.6-luna` / `gpt-5.6-sol` / `gpt-5.6-terra` |
| GPT-6 Astra | `gpt-6-astra` |
| MAI-Code-1.1-Flash | `mai-code-1.1-flash` |

A wrong id is corrected in the provider's model list; no code change is needed.

## Appendix B: thinking levels

| UI | Value |
| --- | --- |
| Low | `low` |
| Medium | `medium` |
| High | `high` (default) |
| Extra high | `xhigh` |
| Max | `max` |

## Appendix C: related API endpoints

Everything the UI uses lives under `/api`; the full list is in [API](api.md) and the interactive
documentation is served by the API at `/docs`. Provider endpoints: `/api/llm-providers`,
`/api/llm-providers/catalog`, `/api/llm-providers/{id}/test`,
`/api/llm-providers/{id}/github-device/start`, and `/check`. Starting an analysis and chatting are
`POST /api/cases/{case_id}/analysis-runs` and `POST /api/chat/stream`; both accept `provider_id`,
`model`, and `reasoning_effort`.
