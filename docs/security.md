# Security

## Credentials

GitHub source OAuth and Copilot plugin tokens are never returned to frontend responses. The metadata store saves encrypted token material and only exposes status fields such as `authorized`, `token_type`, `runtime_type`, and `has_copilot_credential`.

Credential retrieval is backend-only. Store implementations expose encrypted credential records by type, and only the Copilot model gateway decrypts them immediately before resolving a plugin token. Stored source OAuth tokens are exchanged against GitHub Copilot's internal token endpoint, and returned plugin tokens are cached with nullable `expires_at` metadata. Expired or revoked credentials are not treated as usable Copilot auth.

Users can disconnect GitHub Copilot with `DELETE /api/copilot/auth/credential`, which revokes stored source and plugin credentials and returns no token material or token hints. Production must replace local encryption key handling with KMS-backed keys. Transport and gateway errors redact known GitHub source-token prefixes and exact plugin/source tokens before surfacing messages.

## Log Redaction

The pipeline redacts before model calls. Supported masks include:

- `<EMAIL>`
- `<IP>`
- `<TOKEN>`
- `<SECRET>`
- `<API_KEY>`
- `<JWT>`
- `<UUID>`
- `<CARD>`
- `<TENANT_ID>`

URL query parameters such as `token`, `password`, `secret`, `api_key`, and `access_token` have their values replaced.

## Causal Safety

Causal graph edges are candidates, not facts. Summaries must use cautious language such as `candidate cause`, `likely`, `evidence suggests`, and `needs validation`.

## Access Control

The API enforces RBAC on every case route. Global `admin` users can access all cases and admin
APIs. Global `engineer` users can create cases and access only cases they own or collaborate on.
Case collaborators have `owner`, `editor`, or `viewer` roles. Owners can manage collaborators,
editors can upload/start analysis/submit feedback/create exports, and viewers can read case,
run, event, report, log, and chat context views only. Inaccessible read routes return `404` to
avoid exposing case existence; mutating routes return `403` when the case is known but the role is
insufficient.

## Audit and Retention

The API persists audit events for case creation, collaborator add/remove, analysis
start/complete/fail, raw-log search access, export creation, feedback submission, admin user
role/active changes, and retention runs. Admin audit APIs omit IP/user-agent fields and sanitize
metadata so raw log text, credential material, database URLs, tokens, and secrets are not returned.

Retention defaults are declared in `.env.example`. Running retention deletes old audit logs,
scrubs old raw log text to a retained marker while preserving normalized evidence/report rows,
deletes old export rows, and conservatively clears SQLAlchemy `analysis_runs.result_json` only when
fan-out report tables can still serve reports.
