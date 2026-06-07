# API

The current FastAPI app exposes the required foundation routes under `/api`.

## Auth

- `POST /api/auth/register`
- `POST /api/auth/login`
- `POST /api/auth/logout`
- `GET /api/auth/me`

Sessions use an HttpOnly `logan_session` cookie and are revocable in the local store.
`GET /api/auth/me` returns safe user fields including `role`, `is_active`, and
`has_copilot_credential`.

## Access Control

Global roles are `admin` and `engineer`. Admins can access all cases and admin APIs. Engineers
can create cases and access only their own or collaborator cases. Case collaborators use
`owner`, `editor`, and `viewer`: owners can manage collaborators and edit; editors can upload,
start analysis, submit feedback, and create exports; viewers can read case/report/event/log
views only. Case creators are automatically owners.

Read routes such as `GET /api/cases/{case_id}` and report/event/log routes return `404` for
inaccessible cases. Mutating case routes return `403` when the case exists but the caller lacks
the needed collaborator role.

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
- `GET /api/cases/{case_id}/collaborators`
- `POST /api/cases/{case_id}/collaborators`
- `DELETE /api/cases/{case_id}/collaborators/{user_id}`
- `POST /api/cases/{case_id}/uploads`
- `PUT /api/cases/{case_id}/uploads/{file_id}/content`
- `GET /api/cases/{case_id}/uploads/{file_id}/multipart`
- `DELETE /api/cases/{case_id}/uploads/{file_id}/multipart`
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
`s3://bucket/cases/{case_id}/uploads/{file_id}/{safe_filename}` object URI. Smaller files keep the
existing single presigned `PUT` behavior and the response includes `upload_mode: "single"`,
`upload_url`, `upload_headers`, and `expires_in`; `object_uri` is not exposed publicly.

S3/MinIO raw uploads switch to multipart when `multipart: true` is passed to
`POST /uploads`, or when `size_bytes >= LOGAN_S3_MULTIPART_THRESHOLD_BYTES` (default
100 MiB). The response includes `upload_mode: "multipart"`, `multipart_upload_id`,
`part_size_bytes`, `part_count`, `parts` with `{part_number, upload_url, upload_headers}`, and
`expires_in`. The API rejects plans whose part count exceeds
`LOGAN_S3_MULTIPART_MAX_PARTS` (default 10000). `LOGAN_S3_MULTIPART_PART_SIZE_BYTES` defaults to
64 MiB and can be overridden per request with `part_size_bytes`.

Clients upload each part directly to S3/MinIO, collect ETags, compute SHA-256 locally, then call
`POST /complete` with `sha256`, matching `multipart_upload_id`, and
`parts: [{part_number, etag}]`. Completion calls S3 `complete_multipart_upload`, verifies
existence and size with `head_object`, and stores the client digest without reading the full
object. `GET /multipart` returns fresh part URLs and any uploaded parts reported by S3
`list_parts`, allowing clients that persisted `file_id` to resume. `DELETE /multipart` aborts the
S3 multipart upload and records `aborted_at` in safe upload metadata. Local uploads do not use
multipart and remain direct authenticated API `PUT` uploads.

For single S3/MinIO uploads, browser clients upload directly to object storage, compute SHA-256
locally, then call `POST /complete` with the digest. The completion route verifies existence and
size with `head_object`. If object metadata contains `sha256`, it must match the client digest;
otherwise the verified client digest is stored. The API does not read full S3 objects during
completion.

`POST /complete` is idempotent for matching sha256 values and returns `409` for conflicting
sha256 values.

`POST /api/cases/{case_id}/analysis-runs` accepts `input_file_ids` for completed uploads and
converts local `file://` object URIs to filesystem paths. S3/MinIO-backed completed uploads pass
their internal `s3://` object URI into the selected orchestrator. The local API orchestrator and
Temporal worker materialize S3 objects into `LOGAN_ANALYSIS_INPUT_TMP_DIR` before invoking
`AnalyzeCasePipeline`, then remove those temporary files when the pipeline call exits. Missing
uploads, wrong-case uploads, incomplete uploads, unsupported object URI schemes, and missing local
content return explicit `404` or `400` responses. For local tests, the route also accepts
`input_paths`; plain paths are passed through, `file://` values are converted to filesystem paths,
and `s3://` values are materialized the same way as completed upload ids. When no paths or file ids
are provided, the local synchronous store path uses the checkout incident fixture files for
deterministic development and tests.
`GET /api/cases/{case_id}/analysis-runs` returns `items` with `analysis_run_id`, `run_number`, `status`, `current_step`, `progress`, `started_at`, `completed_at`, `error_message`, `model_provider`, and `model_name`.
`GET /api/cases/{case_id}/analysis-runs/{run_id}/artifacts` requires case view permission and
returns step artifact rows with `object_uri`, `sha256`, `size_bytes`, and safe metadata only. It
does not return artifact JSON body content.

Collaborator management requires case owner or global admin access. `POST /collaborators`
accepts `user_id` and role (`owner`, `editor`, or `viewer`) and upserts the collaborator.
Add/remove operations are audited.

## Reports

- `GET /api/cases/{case_id}/analysis-runs/{run_id}/summary`
- `GET /api/cases/{case_id}/analysis-runs/{run_id}/temporal`
- `GET /api/cases/{case_id}/analysis-runs/{run_id}/logs`
- `GET /api/cases/{case_id}/analysis-runs/{run_id}/causal-graph`
- `GET /api/cases/{case_id}/analysis-runs/{run_id}/causal-summary`
- `PATCH /api/cases/{case_id}/analysis-runs/{run_id}/causal-summary`
- `POST /api/cases/{case_id}/analysis-runs/{run_id}/exports`
- `POST /api/cases/{case_id}/feedback`

Report responses are generated from the stored analysis result, not static fixtures.
`PATCH /causal-summary` requires case edit permission and accepts only
`summary_markdown` (required, 1-12000 characters) plus optional
`customer_update_markdown` (up to 12000 characters; omit or send `null` to keep the current
customer update). The response has the same shape as `GET /causal-summary` and returns
`edited: true`; evidence refs, confidence, and next actions remain graph-generated evidence and
are not accepted in the update request. Edits are audited as `causal_summary.edit` with summary
lengths and evidence counts only, never raw logs, prompts, tokens, or secrets. Causal-summary
exports are generated from the current summary, including edited summaries and SQL fan-out
fallback when retained report rows exist.

## Admin

- `GET /api/admin/users`
- `PATCH /api/admin/users/{user_id}`
- `GET /api/admin/audit-logs`
- `GET /api/admin/settings`
- `POST /api/admin/retention/run`

Admin routes require a global `admin` role. User patch accepts `role` and/or `is_active` and
records audit events. Audit log listing supports `case_id`, `action`, `user_id`, `limit`, and
`offset`. Analysis completion records `model.invocation` with only safe model invocation metadata:
`analysis_run_id`, model provider/name/reasoning effort, `prompt_version`, representative sample
or model-input counts, annotation/template counts, and `redacted: true`. It never includes raw or
redacted log lines, prompt bodies, model input payloads, representative line text, tokens,
credentials, secrets, or file paths. Settings returns only safe runtime shape: env, store backend,
object backend,
orchestrator, retention days, rate-limit settings, and analytics toggles. It does not return
secrets, database URLs, access keys, tokens, credential hints, or raw log text.

Retention run responses return:

- `audit_logs_deleted`
- `raw_log_lines_scrubbed`
- `exports_deleted`
- `analysis_results_cleared`
- `step_artifacts_deleted`

## Rate Limiting

Set `LOGAN_RATE_LIMIT_ENABLED=true` to enable the built-in fixed-window API limiter.
`LOGAN_RATE_LIMIT_REQUESTS_PER_MINUTE` defaults to `120`. Requests are keyed by hashed
`logan_session` cookie when present and by client IP otherwise. Exceeded requests return JSON
`429` with a clear `detail` and `Retry-After`.
