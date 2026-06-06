# Security

## Credentials

GitHub source OAuth and Copilot plugin tokens are never returned to frontend responses. The local store saves encrypted or mock-encrypted token material and only exposes status fields such as `authorized` and `has_copilot_credential`.

Production must replace local encryption key handling with KMS-backed keys and add credential revocation endpoints.

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

The API has audit-log model shape and export/feedback capture. Production stages must persist audit events for raw-log access, export generation, feedback, and model invocation metadata. Retention defaults are declared in `.env.example`.
