# LogAn Web

`apps/web` is the browser workbench for LogAn. Engineers authenticate, create incident cases,
upload evidence, start analysis runs, monitor progress, and move between five linked report views.
The web application owns presentation and browser interaction; domain processing, authorization,
persistence, and redaction remain in `apps/api`.

Start with the repository [README](../../README.md), [user guide](../../docs/user-guide.md), and
[architecture](../../docs/architecture.md) for the complete workflow.

## Responsibilities

The web application provides:

- login and logout navigation;
- the authenticated application shell and case list;
- case creation, editing, deletion, and run history;
- local upload progress and analysis controls;
- polling for active analysis-run progress;
- Data Summary, Temporal View, Tabular Logs, Causal Graph, and Causal Summary;
- evidence inspection and links between report views;
- AI chat for completed AI Platform runs.

It calls the API directly from the browser. It does not connect to SQLite, read uploaded files from
disk, or run analysis algorithms.

## Technology

- Next.js 16 App Router
- React 19 and TypeScript in strict mode
- Material UI 9 with Emotion
- ECharts 6 for temporal activity
- Cytoscape.js for causal graphs
- `react-markdown`, `remark-gfm`, and `rehype-sanitize`
- ESLint with the Next.js configuration

The application is the `@logan/web` npm workspace. Install dependencies from the repository root
so the root `package-lock.json` remains authoritative.

## Directory layout

```text
apps/web/
├── package.json
├── next.config.ts
├── eslint.config.mjs
├── tsconfig.json
└── src/
    ├── app/
    │   ├── layout.tsx              # root HTML and providers
    │   ├── providers.tsx           # MUI cache, theme, and CSS baseline
    │   ├── page.tsx                # redirects / to /cases
    │   ├── login/page.tsx          # starts the API-selected login flow
    │   ├── healthz/route.ts        # web-container health endpoint
    │   └── (app)/
    │       ├── layout.tsx          # authenticated Shell wrapper
    │       └── cases/
    │           ├── page.tsx        # case list
    │           ├── new/page.tsx    # create, upload, and analyze
    │           └── [caseId]/
    │               ├── page.tsx    # case workspace
    │               └── runs/[runId]/
    │                   ├── layout.tsx
    │                   ├── summary/page.tsx
    │                   ├── temporal/page.tsx
    │                   ├── logs/page.tsx
    │                   ├── causal-graph/page.tsx
    │                   └── causal-summary/page.tsx
    ├── components/
    │   ├── Shell.tsx
    │   ├── AnalysisProgressPanel.tsx
    │   ├── CaseAnalysisNav.tsx
    │   ├── CaseRunInspector.tsx
    │   ├── FileUploadDropzone.tsx
    │   ├── ChatWorkspace.tsx
    │   ├── Evidence.tsx
    │   ├── MarkdownMessage.tsx
    │   └── ui.tsx
    ├── lib/
    │   ├── api.ts                  # domain types and API methods
    │   ├── api/http.ts             # fetch, errors, query strings, XHR upload
    │   ├── auth.ts                 # login URL builder
    │   ├── navigation.ts           # safe redirect path handling
    │   ├── signals.ts              # golden-signal semantics and colors
    │   └── format.ts
    └── theme.ts
```

## Routing and layouts

The `src/app/(app)` directory is a Next.js route group. Parentheses organize authenticated pages
under one `Shell` layout without adding `/app` to the URL.

| File area | Browser route | Purpose |
| --- | --- | --- |
| `app/page.tsx` | `/` | redirect to the case list |
| `app/login/page.tsx` | `/login` | start login and preserve a safe `next` path |
| `app/(app)/cases/page.tsx` | `/cases` | browse and filter cases |
| `app/(app)/cases/new/page.tsx` | `/cases/new` | create a case and optionally start analysis |
| `app/(app)/cases/[caseId]/page.tsx` | `/cases/{caseId}` | workspace, files, runs, progress, chat |
| `runs/[runId]/summary` | `/cases/{caseId}/runs/{runId}/summary` | Data Summary |
| `runs/[runId]/temporal` | `/cases/{caseId}/runs/{runId}/temporal` | Temporal View |
| `runs/[runId]/logs` | `/cases/{caseId}/runs/{runId}/logs` | Tabular Logs |
| `runs/[runId]/causal-graph` | `/cases/{caseId}/runs/{runId}/causal-graph` | Causal Graph |
| `runs/[runId]/causal-summary` | `/cases/{caseId}/runs/{runId}/causal-summary` | Causal Summary |

The public login page sits outside the route group. Authenticated pages call `/api/auth/me` when
the `Shell` mounts. A missing or expired session redirects to `/login` with the current path.

## Domain concepts

| Term | Meaning in the interface |
| --- | --- |
| Case | An incident workspace containing context, uploads, and numbered analysis runs |
| Analysis run | One execution over selected completed uploads, with independent status and reports |
| Template | A repeated redacted log pattern representing one or more normalized lines |
| Golden signal | The classification axis shared by summary, temporal, logs, and graph views |
| Evidence reference | A case/run-scoped pointer to a redacted file and line location |
| Causal candidate | A ranked relationship that requires investigation and validation |

## API integration

`src/lib/api/http.ts` is the shared HTTP layer. It:

- prefixes paths with `NEXT_PUBLIC_API_BASE_URL`;
- sends `credentials: "include"` on API requests;
- serializes JSON bodies and query parameters;
- converts non-success responses to `ApiError`;
- uses `XMLHttpRequest` for upload progress.

`src/lib/api.ts` defines the browser-side request and response types plus four clients:

| Client | Responsibility |
| --- | --- |
| `authApi` | current session and logout |
| `casesApi` | cases, upload reservation, content upload |
| `runsApi` | list, start, inspect, and cancel runs |
| `reportsApi` | the five report endpoints |
| `chatApi` | parse streaming chat SSE events |

These TypeScript interfaces are a maintained browser view of the backend contract. When a backend
route or schema changes, update this file with the OpenAPI snapshot and related pages.

### Authentication

`/login` redirects the browser to `GET /api/auth/login`. The API chooses the configured mode:
development can use the local default user, while configured environments use SSO. The API sets
the HTTP-only `logan_session` cookie and redirects back to the safe `next` path.

The web app never reads the cookie value. All browser requests rely on credentialed fetches, so
the API CORS origins and the browser-visible web origin must agree.

### Uploads and analysis runs

Uploads use two requests:

1. create upload metadata and receive a generated content URL;
2. PUT the exact file bytes while reporting browser progress.

The client validates non-empty files and the 100 MiB limit before starting. Files are uploaded in
sequence. Analysis starts with the completed file ids.

The case workspace polls run state until it reaches `completed`, `failed`, or `cancelled`.
`AnalysisProgressPanel.tsx` mirrors the API pipeline step names and must change with the backend
pipeline.

### Reports and evidence

The report navigation keeps every page scoped to a case id and run id:

- Data Summary groups templates and supports attention/all scopes.
- Temporal View uses ECharts and links selected windows to logs.
- Tabular Logs supports query, service, window, and pagination filters.
- Causal Graph renders ranked candidate relationships with Cytoscape.js.
- Causal Summary renders evidence-bound Markdown and validation actions.

`Evidence.tsx` renders source references shared by report and chat results. Model-generated
Markdown passes through `rehype-sanitize`; keep URL and HTML restrictions intact.

### Chat

Chat is available only for a completed run created with `LOGAN_LLM_PROVIDER=ai_platform`.
`chatApi.stream()` parses `evidence`, `delta`, `done`, and `error` server-sent events from
`POST /api/chat/stream`. Chat history lives in the current page and is not persisted.

## State and UI conventions

- Pages and components use local React state and effects; there is no global state library.
- `Shell.tsx` owns session status, the sidebar case list, and sign-out.
- Case changes dispatch `logan:case-saved` and `logan:case-deleted` browser events so the sidebar
  updates without a global store.
- Shared buttons, cards, badges, empty states, and status tones belong in `components/ui.tsx`.
- Theme tokens and MUI component overrides belong in `theme.ts`.
- Golden-signal order, labels, and colors belong in `lib/signals.ts`.
- ECharts and Cytoscape containers require explicit height and their instances must be disposed
  during effect cleanup.

## Configuration

The web application has one public setting:

```text
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
```

It defaults to `http://localhost:8000`. The value is available to browser code and is fixed when a
production build is created, so rebuild the web image after changing it.

For cross-origin local development, the API must allow the web origin and credentialed requests:

```text
LOGAN_WEB_BASE_URL=http://localhost:3000
LOGAN_CORS_ALLOWED_ORIGINS=http://localhost:3000,http://127.0.0.1:3000
```

## Run locally

Install the root workspace dependencies:

```bash
npm ci
```

Start the API first, then run:

```bash
npm run dev --workspace @logan/web
```

The development server is available at `http://localhost:3000`.

On Windows, `scripts\local.bat -WebOnly` starts only the web application.
`scripts\local.bat` installs dependencies, applies API migrations, and starts both applications.

For a production-style server:

```bash
npm run build --workspace @logan/web
npm run start --workspace @logan/web
```

## Validation

Run from the repository root:

```bash
npm run lint
npm run typecheck
npm run build
```

The workspace equivalents are:

```bash
npm run lint --workspace @logan/web
npm run typecheck --workspace @logan/web
npm run build --workspace @logan/web
```

`lint` runs ESLint with warnings treated as errors. `typecheck` runs `tsc --noEmit`. The production
build also compiles routes and verifies the application bundle.

## Common changes

### Add or change an API call

Reuse `request<T>()` from `lib/api/http.ts`, add the domain method and types in `lib/api.ts`, and
handle `ApiError` in the page. Keep `credentials: "include"` centralized in the shared helper.

### Add a report page

Create the page below `app/(app)/cases/[caseId]/runs/[runId]`, add the API response type and method,
and add the destination to `analysisNavItems()` in `CaseAnalysisNav.tsx`. Preserve evidence links
to Tabular Logs where the response exposes source references.

### Change pipeline progress

Update `PIPELINE_STEPS` in `AnalysisProgressPanel.tsx` at the same time as
`apps/api/logan_analysis/pipeline.py` and `docs/analysis-pipeline.md`.

### Change shared presentation

Use `components/ui.tsx` for reusable controls, `theme.ts` for application-wide Material UI tokens,
and `lib/signals.ts` for golden-signal semantics. Avoid defining a second status or signal palette
inside a page.

## Common pitfalls

- Starting the web server without `npm ci` leaves the Next.js executable unavailable.
- Opening `127.0.0.1` while the configured web base URL is `localhost`, or the reverse, can break
  credentialed authentication and development WebSockets.
- `NEXT_PUBLIC_API_BASE_URL` changes require a new production build.
- API requests outside the shared helper can omit cookies or inconsistent error handling.
- The TypeScript API types do not generate themselves from OpenAPI and must be updated explicitly.
- Chart containers without a height render as empty areas.
- Analysis progress is polling; only chat uses server-sent events.

## Reading order

1. `src/app/layout.tsx` and `src/app/providers.tsx`
2. `src/app/(app)/layout.tsx`
3. `src/components/Shell.tsx`
4. `src/lib/api/http.ts`
5. `src/lib/api.ts`
6. `src/app/(app)/cases/new/page.tsx`
7. `src/app/(app)/cases/[caseId]/page.tsx`
8. `src/components/AnalysisProgressPanel.tsx`
9. `src/components/CaseAnalysisNav.tsx`
10. the five report pages under `runs/[runId]`
