# API

The API is served under `/api`. Interactive OpenAPI documentation is available at `/docs`.

## Authentication

- `GET /api/auth/login`
- `GET /api/auth/sso/callback`
- `GET /api/auth/me`
- `POST /api/auth/logout`

In development, the login endpoint creates a session for the local default user when
`LOGAN_SSO_AUTHORIZE_URL` is empty. Otherwise it begins the configured SSO flow.

## Cases and uploads

- `GET /api/cases`
- `POST /api/cases`
- `GET /api/cases/{case_id}`
- `PATCH /api/cases/{case_id}`
- `DELETE /api/cases/{case_id}`
- `POST /api/cases/{case_id}/uploads`
- `PUT /api/cases/{case_id}/uploads/{file_id}/content`

Each upload must contain at least one byte. The default maximum is 300 MiB, configured in bytes
with `LOGAN_MAX_UPLOAD_BYTES`. The same configured limit applies to the combined expanded contents
of an archive.

## Analysis runs

- `POST /api/cases/{case_id}/analysis-runs`
- `GET /api/cases/{case_id}/analysis-runs`
- `GET /api/cases/{case_id}/analysis-runs/{run_id}`
- `POST /api/cases/{case_id}/analysis-runs/{run_id}/cancel`

Starting a run requires at least one completed `input_file_id`. Optional `provider_id`, `model`,
and `reasoning_effort` select the AI provider, one of its enabled models, and the thinking level
(`low`, `medium`, `high`, `xhigh`, or `max`); without `provider_id` the run is deterministic. The
API returns the queued run and continues analysis in the background. Run responses include
`llm_provider_id`, `llm_provider_name`, and `reasoning_effort`.

## Reports

- `GET /api/cases/{case_id}/analysis-runs/{run_id}/summary`
- `GET /api/cases/{case_id}/analysis-runs/{run_id}/temporal`
- `GET /api/cases/{case_id}/analysis-runs/{run_id}/logs`
- `GET /api/cases/{case_id}/analysis-runs/{run_id}/causal-graph`
- `GET /api/cases/{case_id}/analysis-runs/{run_id}/causal-summary`

## AI providers

- `GET /api/llm-providers/catalog`
- `GET /api/llm-providers`
- `POST /api/llm-providers`
- `GET /api/llm-providers/{provider_id}`
- `PATCH /api/llm-providers/{provider_id}`
- `DELETE /api/llm-providers/{provider_id}`
- `POST /api/llm-providers/{provider_id}/test`
- `POST /api/llm-providers/{provider_id}/github-device/start`
- `POST /api/llm-providers/{provider_id}/github-device/check`

Providers are scoped to the signed-in user. `provider_type` is `ai_platform` or
`github_copilot`. `config` holds non-secret settings and `secrets` holds credentials; responses
list stored secrets by field name only. The catalog returns the supported provider types, their
model lists, the thinking levels, and the deployment defaults for AI Platform endpoints. The
GitHub device endpoints start the Copilot device flow and poll it; a successful check stores the
token on the provider.

## Chat and health

- `POST /api/chat/stream`
- `GET /healthz`

Chat requires a completed analysis run, access to its case, and a connected AI provider. The
request may name `provider_id`, `model`, and `reasoning_effort`; otherwise the run's provider or
the user's default provider answers. The stream starts with a `meta` event naming the provider,
model, and thinking level used.
