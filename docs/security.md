# Security

Production authentication uses SSO. The callback provisions a local profile from the external
subject, email, and username. Development uses a single local default user when
`LOGAN_SSO_AUTHORIZE_URL` is empty. Browser sessions use a random token in an HTTP-only, same-site
cookie; only its SHA-256 hash is stored.

Each case belongs to the user who created it. Case, upload, run, report, and chat routes verify that
ownership before returning data.

Uploads are written below `LOGAN_LOCAL_OBJECT_STORE_DIR` using generated case and file identifiers
and sanitized filenames. Analysis accepts completed upload identifiers, not arbitrary filesystem
paths.

Log preprocessing masks common secrets before model input or report display. Analysis progress
contains pipeline-generated counts. Model requests contain bounded, redacted case context,
representative samples, and evidence; runtime routing settings and full source paths are excluded.
Error messages are sanitized before storage, and failure logs do not include exception content.

AI provider credentials (AI Platform passwords or trust tokens, GitHub access tokens) are stored
per user in the `llm_providers` table, encrypted with a key derived from `LOGAN_SECRET_KEY`. API
responses expose secrets by field name only. The GitHub Copilot device flow keeps the pending
authorization in process memory scoped to the requesting user and stores the resulting token
server-side; the browser only ever sees the one-time user code. Copilot session tokens obtained
from GitHub are cached in memory and never persisted.

For production:

- use HTTPS for the web app, API, SSO provider, and AI providers
- set a unique `LOGAN_SECRET_KEY` and keep it stable; rotating it invalidates stored provider
  credentials
- configure the SSO authorize URL, token URL, and client id
- keep TLS verification enabled
- restrict CORS to the deployed web origin
- restrict access to the database and local upload directory
- keep `.env` out of source control

See [Reliability and explainability](reliability-and-explainability.md) for model boundaries,
evidence validation, and current operational limits.
