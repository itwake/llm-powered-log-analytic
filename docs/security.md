# Security

## Credentials

AI Platform trust tokens, usernames, passwords, and other credential material are never returned
to frontend responses. Backend configuration is read from `LOGAN_AI_PLATFORM_*` settings, and
runtime errors redact known token prefixes plus exact credential values before surfacing messages.

Credential encryption supports key ids for rotation. New credentials are stored with
`LOGAN_CREDENTIAL_ENCRYPTION_KEY_ID` and are encrypted with `LOGAN_CREDENTIAL_ENCRYPTION_KEY`.
`LOGAN_CREDENTIAL_ENCRYPTION_KEYRING` can be a JSON object such as
`{"2026-01":"old-key","2026-06":"new-key"}` or a comma-separated `id=value` list. The current
`LOGAN_CREDENTIAL_ENCRYPTION_KEY_ID` is always bound to `LOGAN_CREDENTIAL_ENCRYPTION_KEY`; older
ids remain decrypt-only while they are present in the keyring.

Rotation boundary:

- Add the old key to `LOGAN_CREDENTIAL_ENCRYPTION_KEYRING`.
- Change `LOGAN_CREDENTIAL_ENCRYPTION_KEY_ID` and `LOGAN_CREDENTIAL_ENCRYPTION_KEY` for new writes.
- Restart API workers so the keyring is loaded consistently.
- Keep old keys until all active stored credentials have been reissued or revoked.

Legacy credentials without a key id are still decryptable by trying the current key and configured
keyring values. The API never logs key material, keyring values, encrypted token bytes, token hints,
or decrypted credentials.

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

The API enforces organization isolation and RBAC on every case route. Registered users join the
default organization unless provisioned otherwise. Admin users can administer only their own
organization's users, cases, policy groups, and audit rows. Engineers can create cases and access
only same-organization cases they own, collaborate on, or receive through policy group grants.

Case collaborators and case policy-group grants have `owner`, `editor`, or `viewer` roles. Owners
can manage collaborators, editors can upload/start analysis/submit feedback/create exports, and
viewers can read case, run, event, report, log, and chat context views only. Inaccessible read
routes return `404` to avoid exposing case existence; mutating routes return `403` when the case is
known but the role is insufficient. Cross-organization user, collaborator, group, and case grants
are rejected.

SCIM 2.0 style `/api/scim/v2/Users` and `/api/scim/v2/Groups` endpoints accept either an admin
session or a bearer token configured with `LOGAN_SCIM_BEARER_TOKEN`. Admin-session requests are
scoped to the admin user's own organization. Bearer-token requests are scoped to
`LOGAN_SCIM_ORGANIZATION_ID`, which defaults to `default`; the API creates that organization on
first SCIM bearer use if it does not already exist. SCIM responses never include passwords,
credential tokens, token hints, or secret material. SCIM create, update, patch, deactivate, and
group membership sync operations write security audit events.

## Audit and Retention

The API persists audit events for case creation, collaborator add/remove, analysis
start/complete/fail, raw-log search access, export creation, feedback submission, admin user
role/active changes, and retention runs. Admin audit APIs omit IP/user-agent fields and sanitize
metadata so raw log text, credential material, database URLs, tokens, and secrets are not returned.

Retention defaults are declared in `.env.example`. Running retention deletes old audit logs,
scrubs old raw log text to a retained marker while preserving normalized evidence/report rows,
deletes old export rows, deletes old step artifact records, and conservatively clears SQLAlchemy
`analysis_runs.result_json` only when fan-out report tables can still serve reports.
