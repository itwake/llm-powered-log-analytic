# API

The API is served under `/api`. Interactive OpenAPI documentation is available at `/docs`.

## Authentication

- `GET /api/auth/sso/login`
- `GET /api/auth/sso/callback`
- `GET /api/auth/me`
- `POST /api/auth/logout`

## Cases and uploads

- `GET /api/cases`
- `POST /api/cases`
- `GET /api/cases/{case_id}`
- `PATCH /api/cases/{case_id}`
- `DELETE /api/cases/{case_id}`
- `POST /api/cases/{case_id}/uploads`
- `PUT /api/cases/{case_id}/uploads/{file_id}/content`

## Analysis runs

- `POST /api/cases/{case_id}/analysis-runs`
- `GET /api/cases/{case_id}/analysis-runs`
- `GET /api/cases/{case_id}/analysis-runs/{run_id}`
- `POST /api/cases/{case_id}/analysis-runs/{run_id}/cancel`

Starting a run requires at least one completed `input_file_id`. The API returns the queued run and
continues analysis in the background.

## Reports

- `GET /api/cases/{case_id}/analysis-runs/{run_id}/summary`
- `GET /api/cases/{case_id}/analysis-runs/{run_id}/temporal`
- `GET /api/cases/{case_id}/analysis-runs/{run_id}/logs`
- `GET /api/cases/{case_id}/analysis-runs/{run_id}/causal-graph`
- `GET /api/cases/{case_id}/analysis-runs/{run_id}/causal-summary`

## Chat and health

- `POST /api/chat/stream`
- `GET /healthz`

Chat requires `LOGAN_LLM_PROVIDER=ai_platform`, a completed analysis run, and access to its case.
