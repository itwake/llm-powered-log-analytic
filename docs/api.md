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

Default app construction uses GitHub's real device-code flow with client id `Iv1.b507a08c87ecfe98`.
`/start` posts to `https://github.com/login/device/code` and returns only:

- `auth_id`
- `device_code`
- `user_code`
- `verification_uri`
- `verification_uri_complete`
- `expires_in`
- `interval`

`github_base_url` is accepted in `/start` requests for backwards compatibility only. Copilot OAuth
always uses public `https://github.com`, and auth records store that public GitHub base URL.

`/check` polls `https://github.com/login/oauth/access_token`, respects GitHub `interval` and
`slow_down`, and returns pending, authorized, declined, expired, or not-found status fields.
Authorized responses return `token_type=github_source_oauth`, `runtime_type=github_copilot`,
and `expires_at`; they never include source tokens, plugin tokens, or encrypted bytes.

Tests and local no-network checks inject a deterministic fake client through `create_app(...)`.

## Platform

- `GET /api/capabilities`
- `POST /api/chat`
- `POST /api/tasks/execute`

The model provider is `github_copilot` by default and the default model is `gpt-5.4`.
The backend model gateway resolves credentials in this order:

- stored `copilot_plugin_token`
- stored `github_source_oauth`, exchanged via `https://api.github.com/copilot_internal/v2/token`
- `LOGAN_GITHUB_COPILOT_TOKEN`
- `LOGAN_GITHUB_SOURCE_TOKEN`, exchanged per call

The gateway posts non-streaming requests to `<copilot api base>/responses` with Copilot preview
headers. It returns parsed backend objects with the original provider JSON, `output_text`, and
`output_json` when `response_format={"type": "json_object"}` and the output text is valid JSON.
Streaming `/responses` and `/api/chat/stream` are deferred to the next runtime stage.

## Cases and Analysis

- `POST /api/cases`
- `GET /api/cases`
- `GET /api/cases/{case_id}`
- `POST /api/cases/{case_id}/uploads`
- `PUT /api/cases/{case_id}/uploads/{file_id}/content`
- `POST /api/cases/{case_id}/uploads/{file_id}/complete`
- `POST /api/cases/{case_id}/analysis-runs`
- `GET /api/cases/{case_id}/analysis-runs`
- `GET /api/cases/{case_id}/analysis-runs/{run_id}`

`POST /api/cases/{case_id}/uploads` creates metadata and returns an API `upload_url`. With the
default `LOGAN_OBJECT_STORE_BACKEND=local`, clients `PUT` raw file bytes to that URL. The API
writes bytes under `LOGAN_LOCAL_OBJECT_STORE_DIR`, computes sha256 and size, marks the upload
complete, and stores a local `file://` object URI. `POST /complete` is idempotent for matching
sha256 values and returns `409` for conflicting sha256 values.

`POST /api/cases/{case_id}/analysis-runs` accepts `input_file_ids` for completed uploads and
converts local `file://` object URIs to filesystem paths before invoking the synchronous worker
pipeline. Missing uploads, wrong-case uploads, incomplete uploads, non-file-backed uploads, and
missing local content return explicit `404` or `400` responses. For local tests, the route also
accepts `input_paths`. When no paths or file ids are provided, the local synchronous store path
uses the checkout incident fixture files for deterministic development and tests.
`GET /api/cases/{case_id}/analysis-runs` returns `items` with `analysis_run_id`, `run_number`, `status`, `current_step`, `progress`, `started_at`, `completed_at`, `error_message`, `model_provider`, and `model_name`.

## Reports

- `GET /api/cases/{case_id}/analysis-runs/{run_id}/summary`
- `GET /api/cases/{case_id}/analysis-runs/{run_id}/temporal`
- `GET /api/cases/{case_id}/analysis-runs/{run_id}/logs`
- `GET /api/cases/{case_id}/analysis-runs/{run_id}/causal-graph`
- `GET /api/cases/{case_id}/analysis-runs/{run_id}/causal-summary`
- `POST /api/cases/{case_id}/analysis-runs/{run_id}/exports`
- `POST /api/cases/{case_id}/feedback`

Report responses are generated from the stored analysis result, not static fixtures.
