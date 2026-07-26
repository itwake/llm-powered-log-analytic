# Security

LogAn accepts SSO authentication only. The callback provisions a local profile from the external
subject, email, and username. Browser sessions use a random token in an HTTP-only, same-site
cookie; only its SHA-256 hash is stored.

Each case belongs to the user who created it. Case, upload, run, report, and chat routes verify that
ownership before returning data.

Uploads are written below `LOGAN_LOCAL_OBJECT_STORE_DIR` using generated case and file identifiers
and sanitized filenames. Analysis accepts completed upload identifiers, not arbitrary filesystem
paths.

Log preprocessing masks common secrets before model input or report display. Analysis progress
contains pipeline-generated counts, and error messages are sanitized before storage. AI Platform
credentials are read from process environment variables and are not stored in the database.

For production:

- use HTTPS for the web app, API, SSO provider, and AI Platform
- set a unique `LOGAN_SECRET_KEY`
- keep TLS verification enabled
- restrict CORS to the deployed web origin
- restrict access to the database and local upload directory
- keep `.env` out of source control

See [Reliability and explainability](reliability-and-explainability.md) for model boundaries,
evidence validation, and current operational limits.
