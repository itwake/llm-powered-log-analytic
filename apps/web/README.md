# LogAn Web (`@logan/web`) — the Incident Workbench

The human-facing surface of the three-app LogAn monorepo. `apps/web` is a Next.js 16 App Router frontend where engineers create incident **cases**, upload logs, launch analysis **runs** (an 11-step pipeline), and explore five linked diagnosis views — Data Summary, Temporal View, Tabular Logs, Causal Graph, Causal Summary — plus a streaming AI chat, evidence inspection, exports, and an admin console. It owns **no business logic and no persistence**: every domain operation is a REST/SSE call to `apps/api`. All redaction and analysis correctness live in the backend; this app is a pure API client. It sits alongside `apps/api` (FastAPI backend) and `apps/workers` (analysis pipeline + Temporal worker). See the root [`README.md`](../../README.md) for the full quick start and env vars and [`CONTRIBUTING.md`](../../CONTRIBUTING.md) for conventions; [`CLAUDE.md`](../../CLAUDE.md) is the architecture crib.

## Tech stack

- **Next.js 16.2.7** — App Router; note nearly every page/component is a `"use client"` Client Component.
- **React 19.1.0** / react-dom 19.1.0.
- **TypeScript 5.8.3** — strict, `moduleResolution: "bundler"`, `@/*` → `./src/*`.
- **MUI Material 9.1.2** + `@mui/icons-material` 9.1.1 + `@mui/material-nextjs` 9.1.1 (`AppRouterCacheProvider`) + `@mui/x-data-grid` 9.7.0.
- **Emotion 11** — MUI's styling engine.
- **ECharts 6.1.0** (tree-shaken `echarts/core`) — Temporal View stacked bar chart.
- **Cytoscape.js 3.34.0** — Causal Graph directed graph.
- **react-markdown 10.1.0** + `rehype-sanitize` 6 + `remark-gfm` 4 — chat and causal-summary rendering.
- **`@playwright/test` ^1.60.0** — declared at the repo **root**, not here; the only behavioral test harness.
- **No ESLint, no Jest/Vitest, no Tailwind.** `lint` and `test` scripts are both just `tsc --noEmit`.

Packaged as the npm workspace `@logan/web` (private, v0.1.0) — the **only** workspace in the root `package.json`. Deps are hoisted from the root `package-lock.json` via `npm ci`. The Docker image is built by `infra/docker/web.Dockerfile` (`NEXT_PUBLIC_API_BASE_URL` is baked in at build time).

## Directory layout

```
apps/web/
├── package.json               # @logan/web manifest; scripts dev/build/start + lint/test (both tsc --noEmit)
├── next.config.ts             # minimal — reactStrictMode only (no webpack/rewrites/CORS proxy)
├── tsconfig.json              # strict, ES2022, bundler resolution, @/* -> ./src/*
└── src/
    ├── proxy.ts               # Next 16 "middleware": edge auth gate; redirects to /login w/o logan_session cookie
    ├── theme.ts               # loganTheme (createTheme, single light mode, indigo #5b5cf6) + loganTokens palette
    ├── app/
    │   ├── layout.tsx         # root layout: <html>, globals.css, <Providers>, metadata
    │   ├── providers.tsx      # AppRouterCacheProvider + ThemeProvider(loganTheme) + CssBaseline
    │   ├── page.tsx           # root route — server-side redirect('/cases')
    │   ├── globals.css        # CSS resets + FIXED heights for .temporal-chart / .cytoscape-container
    │   ├── login/page.tsx     # SSO redirect page (window.location.replace to API SSO login)
    │   ├── register/page.tsx  # re-exports /login
    │   ├── healthz/route.ts   # GET {status:'ok'} for the Docker HEALTHCHECK
    │   └── (app)/             # authenticated route group, wrapped in <Shell>
    │       ├── layout.tsx     # <Shell> chrome (sidebar + header)
    │       ├── cases/                        # case list  + cases/new (create)
    │       ├── cases/[caseId]/               # the case Workspace (upload/analyze/poll/chat/inspect)
    │       │   └── runs/[runId]/             # per-run report area; layout renders CaseAnalysisNav (no index page)
    │       │       ├── summary/              # Data Summary
    │       │       ├── temporal/             # Temporal View (ECharts)
    │       │       ├── logs/                 # Tabular Logs
    │       │       ├── causal-graph/         # Causal Graph (Cytoscape.js)
    │       │       └── causal-summary/       # Causal Summary
    │       ├── settings/ai-platform/         # AI-Platform capabilities page
    │       └── admin/                        # admin console (gated on user.role === 'admin')
    ├── lib/
    │   ├── api.ts             # public compatibility facade, upload API, response interfaces
    │   └── api/               # shared HTTP, analysis, chat, and admin clients
    │   ├── auth.ts            # SSO URL builder
    │   ├── signals.ts         # golden-signal colors/order + text helpers (single source of truth)
    │   ├── analysisConfig.ts  # BACKGROUND_ANALYSIS_CONFIG — default run config
    │   ├── navigation.ts      # safe next-path helper
    │   └── format.ts          # formatting helpers
    └── components/
        ├── Shell.tsx          # sidebar/header chrome + client-side auth guard (authApi.me()); exports Metric card
        ├── ui.tsx             # design-system primitives (Button/Badge/Card/EmptyState/InfoGrid/statusTone…)
        ├── CaseAnalysisNav.tsx    # run report tab nav (analysisNavItems())
        ├── ChatWorkspace.tsx      # streaming AI chat over chatApi.stream (SSE)
        ├── AnalysisProgressPanel.tsx  # hardcoded 11-step PIPELINE_STEPS mirror + run-progress model
        ├── CaseRunInspector.tsx
        ├── Evidence.tsx           # EvidenceChip / EvidenceDetail
        ├── MarkdownMessage.tsx    # hardened markdown (rehype-sanitize, skipHtml, safeHref)
        ├── FileUploadDropzone.tsx
        └── Link.tsx

# Repo ROOT (not in apps/web):
playwright.config.ts           # boots FastAPI + `next dev` as webServers, with mock-SSO LOGAN_* env
tests/e2e/logan.spec.ts        # the browser E2E that drives the whole web + API stack
```

## Routing model — App Router & route groups

Two things called "app" live here, and **neither shows up in the URL** — which is exactly why they're easy to miss:

- **`src/app/`** is the Next.js **App Router root** (a framework-fixed folder name), not a business module. It is the base of the route tree, not a URL segment.
- **`src/app/(app)/`** is a **route group**. In the App Router, a folder wrapped in parentheses organizes routes and shares a layout **without contributing a URL segment**. So pages under `(app)/` render at the bare path — `src/app/(app)/cases/page.tsx` serves `/cases`, **not** `/app/cases`. You never see `app` in the address bar; you only see its *effect*.

Its purpose is to wrap every **authenticated** page in one shared shell while keeping public pages bare:

| File | URL | Chrome |
| --- | --- | --- |
| `src/app/(app)/cases/page.tsx` | `/cases` | `<Shell>` (sidebar + header) |
| `src/app/(app)/cases/[caseId]/page.tsx` | `/cases/<caseId>` | `<Shell>` |
| `src/app/(app)/cases/[caseId]/runs/[runId]/summary/page.tsx` | `/cases/<caseId>/runs/<runId>/summary` | `<Shell>` |
| `src/app/(app)/admin/page.tsx` | `/admin` | `<Shell>` |
| `src/app/(app)/settings/ai-platform/page.tsx` | `/settings/ai-platform` | `<Shell>` |
| `src/app/page.tsx` | `/` | none — server `redirect('/cases')` |
| `src/app/login/page.tsx` | `/login` | none — SSO redirect page |
| `src/app/register/page.tsx` · `src/app/healthz/route.ts` | `/register` · `/healthz` | none |

Layouts nest top-down, each wrapping the level below:

```
src/app/layout.tsx          # root: <html><body><Providers> (MUI cache + theme) — wraps EVERY page
└─ src/app/(app)/layout.tsx # <Shell> (sidebar + header + client auth guard) — wraps only (app)/ pages
   └─ cases / admin / settings/…        # authenticated pages, inside the shell
src/app/login · register · page.tsx     # OUTSIDE (app): root layout only, no Shell
```

Takeaway: `(app)` is a pure code-organization device that lets all signed-in pages share the `<Shell>` chrome (`src/components/Shell.tsx`) without a `/app` prefix leaking into the URL. The sidebar/header you see on every case, admin, and settings page *is* that route group at work — the folder name itself is intentionally invisible.

## How it fits

The web app talks to **`apps/api` only**, and only over HTTP from the browser. There is **no shared package, no shared code, and no server-to-server call** — no relationship to `apps/workers` except through the API and two mirrored constants.

| Contract point | Where | What to keep in sync |
| --- | --- | --- |
| REST + auth | `apps/web/src/lib/api/http.ts` → `${NEXT_PUBLIC_API_BASE_URL}` | Every call uses `credentials:'include'` so the cross-origin `logan_session` cookie is sent; the API's `LOGAN_CORS_ALLOWED_ORIGINS` must allow the web origin **with credentials**. |
| Response types | `apps/web/src/lib/api.ts` interfaces | Hand-maintained mirror of the API's OpenAPI schema (`docs/openapi.snapshot.json`). Route/schema changes must be reflected here or the UI silently breaks. |
| Pipeline steps | `apps/web/src/components/AnalysisProgressPanel.tsx` `PIPELINE_STEPS` | Must match the backend `PIPELINE_STEP_NAMES` order (a coupling to `apps/workers`). |
| Run config | `apps/web/src/lib/analysisConfig.ts` `BACKGROUND_ANALYSIS_CONFIG` | The config the API/worker consume when a run is launched. |
| SSE | `chatApi.stream` → `POST /api/chat/stream` | Expects `event: delta \| evidence \| done \| error` frames. **Analysis progress is polled** (GET run + GET events), not streamed. |
| E2E injection | root `playwright.config.ts` | Wires the web dev server to a mock-SSO API instance. |

## Run it locally

```bash
# From repo root (llm-powered-log-analytic). Install once (hoisted workspace):
npm ci

# 1) Start the API first — the web app is a pure client and does nothing without it.
#    Windows one-shot that loads .env and runs API + web:
scripts\local.ps1
#    …or manually (after loading .env into the process env):
uvicorn app.main:app --reload --app-dir apps/api

# 2) Start the Next dev server on http://localhost:3000, pointed at the API:
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000 npm run dev --workspace @logan/web

# Production-style:
npm run build --workspace @logan/web
npm run start --workspace @logan/web
```

`NEXT_PUBLIC_API_BASE_URL` is the **only** web-specific env var, and it is inlined at build/dev-start time. If empty, `api/http.ts` falls back to same-origin relative calls.

## Test, lint, typecheck

```bash
npm run lint --workspace @logan/web   # === tsc --noEmit  (typecheck only — NOT ESLint)
npm run test --workspace @logan/web   # ALSO === tsc --noEmit  (no unit tests exist)

# Behavioral coverage lives at the repo ROOT as a self-contained Playwright E2E:
npm run e2e:install   # first time only: playwright install chromium
npm run e2e           # boots FastAPI + `next dev` with mock SSO, then runs tests/e2e/logan.spec.ts
```

There is no unit-test runner. `lint` and `test` are identical; the only functional test is the root Playwright spec.

## Key concepts

| Term | Meaning |
| --- | --- |
| **Case** | Top-level incident container (`case_id`, `case_key`, title, product/service/environment, incident_start/end, status). Users create one, upload logs, then run analysis. |
| **Analysis run** | One execution of the 11-step pipeline over a case's inputs (`analysis_run_id`, `run_number`, status, current_step, progress). A case can have many; the UI tracks the latest/active one. |
| **11 pipeline steps** | `ingest_paths → merge_entries → preprocess_redact → drain_templating → representative_sampling → ai_platform_annotation → broadcast_annotations → temporal_aggregation → causal_graph → causal_summary → export_artifacts` — mirrored in `AnalysisProgressPanel`. |
| **Golden signals** | error, availability, saturation, latency, traffic, information, unknown. Each has **one** semantic color (`signals.ts`); **error is always red**. The classification axis across every view. |
| **Template** | A Drain-parsed log pattern (`template_id`, `template_text` with `<*>` placeholders) standing in for many raw lines. The Summary view is one row per template. |
| **Attention vs all** | Summary/graph default to the `attention` scope (error/availability/latency/saturation/traffic); the UI falls back to `all` when a run has no attention templates. |
| **Causal graph** | Nodes (templates ranked by `rank_score`/pagerank), directed edges (cause→symptom) with method/confidence/`needs_validation`, and `root_cause_candidates`. Nothing is asserted as a proven root cause. |
| **Evidence ref** | A redacted pointer to a raw line (`file_path:line_number`, timestamp, `template_id`, `log_id`) making every claim traceable; `EvidenceChip`/`EvidenceDetail` deep-link into Tabular Logs. |
| **Redaction** | Raw text is never shown unredacted — the UI only displays what the backend already redacted. |
| **SSO-only auth** | No passwords; a `logan_session` cookie is the session. Mock SSO is used for local/E2E. |

## Where to start reading

1. `apps/web/package.json` — the stack and the (surprising) script definitions.
2. Root [`CLAUDE.md`](../../CLAUDE.md) + `.env.example` — SSO-only auth, mock provider, and the API/web split.
3. `apps/web/src/proxy.ts` — the edge auth gate and its public-path matcher.
4. `apps/web/src/app/layout.tsx` + `providers.tsx` + `apps/web/src/theme.ts` — bootstrap and theming.
5. `apps/web/src/lib/api.ts` + `apps/web/src/lib/api/` — public facade/types plus focused HTTP, analysis, chat, and admin clients.
6. `apps/web/src/components/Shell.tsx` — sidebar/header chrome and the client-side `me()` auth guard.
7. `apps/web/src/app/(app)/cases/[caseId]/page.tsx` — the workspace tying upload, run polling, chat, and inspector together.
8. `apps/web/src/components/AnalysisProgressPanel.tsx` — the 11-step pipeline mirror and progress model.
9. `apps/web/src/lib/signals.ts` + `apps/web/src/components/ui.tsx` — shared signal semantics and design-system primitives.
10. The five views under `apps/web/src/app/(app)/cases/[caseId]/runs/[runId]/{summary,temporal,logs,causal-graph,causal-summary}/page.tsx` (read `temporal` for ECharts, `causal-graph` for Cytoscape).
11. Root `playwright.config.ts` + `tests/e2e/logan.spec.ts` — the canonical happy path.

## Common tasks

**Add a new report view/tab for a run.** Create `apps/web/src/app/(app)/cases/[caseId]/runs/[runId]/<name>/page.tsx` (client component; `useParams` for `caseId`/`runId`); add a `reportsApi.<name>()` call in `lib/api/analysis.ts` and its response interface in `lib/api.ts`; add the tab to `analysisNavItems()` in `components/CaseAnalysisNav.tsx`. It inherits the run layout (the `CaseAnalysisNav` header) automatically.

**Add or change an API endpoint the UI calls.** Add the method to the focused module under `lib/api/` and its typed request/response interface to the `lib/api.ts` public facade. Reuse the `request<T>()` helper from `lib/api/http.ts` so `credentials:'include'` and error handling stay consistent. Keep the interface in sync with the backend OpenAPI schema.

**Adjust the pipeline step display after a backend change.** Edit the `PIPELINE_STEPS` array in `components/AnalysisProgressPanel.tsx` to match the new backend step names/order. If the default run config changed, update `BACKGROUND_ANALYSIS_CONFIG` in `lib/analysisConfig.ts`.

**Change theming/colors/a shared primitive.** Global palette, typography, and MUI overrides live in `src/theme.ts` (`loganTheme` + `loganTokens`). Shared building blocks (`Button`/`Card`/`Badge`/`EmptyState`…) live in `components/ui.tsx`. Golden-signal colors live in `lib/signals.ts` — change them there so all views stay consistent.

**Work on the Temporal (ECharts) or Causal Graph (Cytoscape) view.** Temporal (`temporal/page.tsx`): `echarts.use()` registers only the needed modules; the option is built in a `useMemo` and applied with `instance.setOption(..., true)`. Graph (`causal-graph/page.tsx`): `cytoscape()` is created in a `useEffect` keyed on data. Both dispose/destroy in cleanup and both rely on the fixed container heights in `globals.css`.

**Run/debug end-to-end.** Start the API, then `npm run dev --workspace @logan/web` with `NEXT_PUBLIC_API_BASE_URL` set. For full-stack browser verification, `npm run e2e` from the repo root boots both servers with mock SSO. Typecheck with `npm run lint --workspace @logan/web`.

## Conventions & gotchas

- **Auth is enforced in two places.** `proxy.ts` (edge) redirects to `/login` when the `logan_session` cookie is absent; `Shell.tsx` (client) calls `authApi.me()` on mount and redirects on 401. There is **no SSO callback page** in the web app — `/login` just `window.location.replace()`s to the API's `/api/auth/sso/login`; the API sets the cookie and 302s back. `/register` re-exports `/login`.
- **`src/proxy.ts` is Next.js 16's renamed middleware** (exports `proxy` + a `config.matcher`). Don't look for `middleware.ts`. The matcher excludes `/api`, `/_next`, favicon, and any path containing a dot.
- **`lint` and `test` are both `tsc --noEmit`.** No Jest/Vitest, no ESLint here. The only behavioral test is the root Playwright spec.
- **Almost everything is a Client Component** (`"use client"`). The only true server pieces are the root `layout`, `page.tsx` (redirect), the `healthz` route, and `proxy.ts`. Data is fetched client-side in `useEffect`, not in Server Components/loaders — there is **no Redux/Zustand/React-Query**; state is local `useState` + `fetch`.
- **Chat is real SSE; analysis progress is polling.** Chat parses a `fetch` `ReadableStream` (manual `\n\n` frame parsing in `api/chat.ts`). Run progress is polled with `setInterval` every 2000ms in the workspace page until a terminal status. Don't confuse the two.
- **`NEXT_PUBLIC_API_BASE_URL` is inlined at build time.** Empty ⇒ same-origin relative calls (fine only if API and web share an origin). In Docker it's an `ARG` baked into the image, so changing it requires a rebuild.
- **Cross-origin cookie auth is fragile.** Every request uses `credentials:'include'`, so a misconfigured `LOGAN_CORS_ALLOWED_ORIGINS` on the API silently breaks all data loading — you get a session but every fetch 401s/CORS-fails.
- **Chart containers need explicit height** from `globals.css` (`.temporal-chart` / `.cytoscape-container`). ECharts and Cytoscape both attach to a ref'd div and must be disposed/destroyed in `useEffect` cleanup; forgetting height ⇒ a zero-size, invisible chart.
- **The Causal Graph draws only the top `MAX_RENDERED_EDGES=20` edges** to avoid a hairball; the full edge list is in the DataGrid below it. Intentional, not a bug.
- **Keep `MarkdownMessage` strict.** It renders model-generated content with `rehype-sanitize`, `skipHtml`, disallowed `img`/`script`/`iframe`/`form`, and `safeHref()` blocking `javascript:` URLs.
- **The sidebar case list uses a lightweight event bus.** Case create/edit/delete flows dispatch window `CustomEvent`s `logan:case-saved` / `logan:case-deleted` that `Shell.tsx` listens for — there is no global store.
- **`api.ts` interfaces are hand-maintained** and can drift from the real API. When the backend contract changes, update them and re-check the OpenAPI snapshot. See [`CONTRIBUTING.md`](../../CONTRIBUTING.md) for the broader conventions.
