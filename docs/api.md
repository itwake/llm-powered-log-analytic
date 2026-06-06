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
- `DELETE /api/copilot/auth/credential`

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

`DELETE /api/copilot/auth/credential` revokes active stored `github_source_oauth` and
`copilot_plugin_token` credentials for the current user and returns only `status` and
`revoked_count`.

Tests and local no-network checks inject a deterministic fake client through `create_app(...)`.

## Platform

- `GET /api/capabilities`
- `POST /api/chat`
- `POST /api/chat/stream`
- `POST /api/tasks/execute`

The model provider is `github_copilot` by default and the default model is `gpt-5.4`.
The backend model gateway resolves credentials in this order:

- stored, non-expired `copilot_plugin_token`
- stored `github_source_oauth`, exchanged via `https://api.github.com/copilot_internal/v2/token`
- `LOGAN_GITHUB_COPILOT_TOKEN`
- `LOGAN_GITHUB_SOURCE_TOKEN`, exchanged per call

Stored source OAuth exchanges cache the returned Copilot plugin token with its parsed `expires_at`.
Environment source tokens are exchanged in memory and are not persisted to user credentials.

The gateway posts requests to `<copilot api base>/responses` with Copilot preview headers.
Non-streaming calls return parsed backend objects with the original provider JSON, `output_text`,
and `output_json` when `response_format={"type": "json_object"}` and the output text is valid
JSON. Streaming calls use `Accept: text/event-stream`, parse provider SSE `data:` frames, normalize
common text-delta shapes into `{"type":"message.delta","delta":"..."}`, and emit
`{"type":"message.completed", ...}` for provider completion or `[DONE]`.

`POST /api/chat/stream` accepts the same `ChatRequest` shape as `POST /api/chat` and requires the
session cookie. Because it is a POST stream, web clients use `fetch` plus `ReadableStream` rather
than `EventSource`. When `case_id` and `analysis_run_id` resolve to an analysis result, the API
sends Copilot a compact redacted context containing the user message, case/run ids, causal summary
text, up to five causal evidence refs, and up to five template-level summary rows. It does not send
raw log text, stored credentials, source tokens, or model prompts. Without context, the endpoint
streams the same clear fallback message as `POST /api/chat` and does not call Copilot.

SSE frames are JSON:

- `event: delta`, `data: {"delta":"..."}`
- `event: evidence`, `data: {"evidence_refs":[...]}`
- `event: done`, `data: {"message":"..."}`
- `event: error`, `data: {"message":"..."}` for sanitized credential or gateway failures

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

`POST /api/cases/{case_id}/uploads` creates metadata and returns an `upload_url`,
`upload_backend`, `upload_headers`, and `expires_in`. With the default
`LOGAN_OBJECT_STORE_BACKEND=local`, the URL is the authenticated API
`PUT /api/cases/{case_id}/uploads/{file_id}/content` route. The API writes bytes under
`LOGAN_LOCAL_OBJECT_STORE_DIR`, computes sha256 and size, marks the upload complete, and stores
a local `file://` object URI. Local responses still include `object_uri` for compatibility.

With `LOGAN_OBJECT_STORE_BACKEND=s3` or `minio`, the API records an internal
`s3://bucket/cases/{case_id}/uploads/{file_id}/{safe_filename}` object URI and returns a
presigned S3/MinIO `PUT` URL plus any headers that the browser must send. Browser clients upload
directly to object storage, compute SHA-256 locally, then call `POST /complete` with the digest.
The completion route verifies existence and size with `head_object`. If object metadata contains
`sha256`, it must match the client digest; otherwise the verified client digest is stored. The API
does not read full S3 objects during completion.

`POST /complete` is idempotent for matching sha256 values and returns `409` for conflicting
sha256 values.

`POST /api/cases/{case_id}/analysis-runs` accepts `input_file_ids` for completed uploads and
converts local `file://` object URIs to filesystem paths before invoking the synchronous worker
pipeline. S3-backed completed uploads currently return `400` for `input_file_ids` because the
local analysis path cannot read non-file-backed uploads until worker-side S3 streaming/download is
implemented. Missing uploads, wrong-case uploads, incomplete uploads, non-file-backed uploads, and
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
