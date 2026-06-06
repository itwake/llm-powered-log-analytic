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

## Audit and Retention

The API persists audit events for case creation, analysis start/complete/fail, raw-log search access, export creation, and feedback submission when the SQLAlchemy store is enabled. Production stages still need admin/UI access, retention jobs, and expanded model-invocation metadata. Retention defaults are declared in `.env.example`.
