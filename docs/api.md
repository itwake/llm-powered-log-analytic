# API

The current FastAPI app exposes the required foundation routes under `/api`.

## Auth

- `POST /api/auth/register`
- `POST /api/auth/login`
- `POST /api/auth/logout`
- `GET /api/auth/me`

Sessions use an HttpOnly `logan_session` cookie and are revocable in the local store.

## Copilot Auth

- `POST /api/copilot/auth/start`
- `POST /api/copilot/auth/check`

The local client is deterministic. It returns a device-code response and authorizes after polling without exposing tokens to the frontend.

## Platform

- `GET /api/capabilities`
- `POST /api/chat`
- `POST /api/tasks/execute`

The model provider is `github_copilot` by default and the default model is `gpt-5.4`.

## Cases and Analysis

- `POST /api/cases`
- `GET /api/cases`
- `GET /api/cases/{case_id}`
- `POST /api/cases/{case_id}/uploads`
- `POST /api/cases/{case_id}/uploads/{file_id}/complete`
- `POST /api/cases/{case_id}/analysis-runs`
- `GET /api/cases/{case_id}/analysis-runs/{run_id}`

For local tests, `POST /api/cases/{case_id}/analysis-runs` accepts `input_paths` in addition to `input_file_ids`, allowing the synchronous pipeline to run against fixture files.

## Reports

- `GET /api/cases/{case_id}/analysis-runs/{run_id}/summary`
- `GET /api/cases/{case_id}/analysis-runs/{run_id}/temporal`
- `GET /api/cases/{case_id}/analysis-runs/{run_id}/logs`
- `GET /api/cases/{case_id}/analysis-runs/{run_id}/causal-graph`
- `GET /api/cases/{case_id}/analysis-runs/{run_id}/causal-summary`
- `POST /api/cases/{case_id}/analysis-runs/{run_id}/exports`
- `POST /api/cases/{case_id}/feedback`

Report responses are generated from the stored analysis result, not static fixtures.
