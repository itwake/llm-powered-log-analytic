# API

The generated OpenAPI contract is available at `/docs`; its committed snapshot is
`docs/openapi.snapshot.json`.

## Authentication and access

- `GET /api/auth/sso/login`
- `GET /api/auth/sso/callback`
- `POST /api/auth/logout`
- `GET /api/auth/me`

Sessions use an HttpOnly `logan_session` cookie. Admins can access all cases. Engineers can access
cases they own or collaborate on. Case roles are `owner`, `editor`, and `viewer`.

## Cases, uploads, and runs

- `POST /api/cases`
- `GET /api/cases`
- `GET|PATCH|DELETE /api/cases/{case_id}`
- collaborator routes below `/api/cases/{case_id}/collaborators`
- `POST /api/cases/{case_id}/uploads`
- `PUT /api/cases/{case_id}/uploads/{file_id}/content`
- `POST /api/cases/{case_id}/analysis-runs`
- run list, status, cancellation, event, and artifact routes

Upload start returns `file_id` and one authenticated `upload_url`. The content route writes the
file below `LOGAN_LOCAL_OBJECT_STORE_DIR`, verifies size, computes SHA-256, and marks the upload
complete in one request. Repeating the same upload is idempotent; different bytes return a
conflict. Analysis accepts completed `input_file_ids`; test and local tooling may also pass
filesystem `input_paths`.

## Reports

- summary
- temporal time-window series
- tabular logs
- causal graph
- causal summary
- exports and feedback

Report reads use normalized SQL rows scoped by case, run, and organization.

## Admin and platform

Admin routes manage users, policy groups, audit logs, safe runtime settings, and retention.
Platform routes expose capabilities, model-backed chat, task execution, health, and Prometheus
metrics.

Raw logs, prompts, credentials, and tokens are excluded from report, progress, artifact, audit,
and metrics metadata.
