# LogAn web

`@logan/web` is the Next.js incident workbench. It contains presentation and API-client code only;
authentication, persistence, uploads, redaction, and analysis remain in `apps/api`.

## Main routes

- `/login` — starts the API-owned SSO flow
- `/cases` and `/cases/new` — case list and creation
- `/cases/[caseId]` — uploads, run launch, progress, and chat
- `/cases/[caseId]/runs/[runId]/summary`
- `/cases/[caseId]/runs/[runId]/temporal` — time-window chart
- `/cases/[caseId]/runs/[runId]/logs`
- `/cases/[caseId]/runs/[runId]/causal-graph`
- `/cases/[caseId]/runs/[runId]/causal-summary`
- `/admin` — users, policy groups, audit, retention, and safe settings

The `(app)` route group adds the authenticated shell without adding a URL segment. Public login and
health routes live outside that group.

## Structure

- `src/lib/api/http.ts` — shared fetch/error handling with cookie credentials
- `src/lib/api/analysis.ts` — run and report requests
- `src/lib/api/chat.ts` — model chat and SSE parsing
- `src/lib/api/admin.ts` — admin requests
- `src/lib/api.ts` — public facade, upload transport, and response interfaces
- `src/components/AnalysisProgressPanel.tsx` — pipeline-step display
- `src/lib/signals.ts` — shared golden-signal order, colors, and labels
- `src/theme.ts` and `src/components/ui.tsx` — theme and common UI primitives

Response interfaces are maintained alongside the frontend client and must track
`docs/openapi.snapshot.json`. Pipeline step names must track
`logan_analysis.observability.PIPELINE_STEP_NAMES`.

## Configuration

`NEXT_PUBLIC_API_BASE_URL` is the only web-specific environment variable. It is inlined at build
time. An empty value uses same-origin API paths; the local two-process setup uses
`http://localhost:8000`.

Every API request sends `credentials: "include"`. Cross-origin development therefore requires the
web origin in `LOGAN_CORS_ALLOWED_ORIGINS`.

## Development

From the repository root:

```bash
npm ci
npm run dev --workspace @logan/web
```

The API must also be running. On Windows, `scripts/local.ps1` or `scripts/local.bat` starts both
processes and loads `.env`.

## Verification

```bash
npm run lint --workspace @logan/web
npm run build --workspace @logan/web
npm run e2e:install
npm run e2e
```

The `lint` and `test` package scripts both run strict TypeScript checking. Behavioral coverage is
the root Playwright flow in `tests/e2e/logan.spec.ts`.

## UI safety

- Model Markdown is rendered through `rehype-sanitize`; raw HTML and unsafe links stay blocked.
- The frontend displays backend-redacted log content only.
- Causal relationships are labeled as candidates requiring validation.
- ECharts and Cytoscape containers require explicit heights and must be disposed during effect
  cleanup.
