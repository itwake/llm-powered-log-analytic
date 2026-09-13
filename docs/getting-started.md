# Getting started

This guide covers local installation on Windows and macOS. LogAn runs two applications:
the FastAPI API on port 8000 and the Next.js web app on port 3000.

## Requirements

- Git
- Python 3.11 or newer
- Node.js 22 or newer with npm
- An OAuth-compatible SSO application when enabling SSO
- Docker Desktop only when using Docker Compose

When using SSO, allow this callback URL for local development:

```text
http://localhost:8000/api/auth/sso/callback
```

## Windows PowerShell

From Command Prompt or PowerShell, the quickest setup is:

```bat
scripts\local.bat
```

The launcher creates `.venv`, installs missing Python and npm dependencies, copies `.env.example`
when `.env` is missing, applies Alembic migrations, opens the web application in a new window, and
runs the API in the current window. The default configuration signs in as the local default user.

Available options are:

- `-ApiOnly`
- `-WebOnly`
- `-SkipInstall`

For a manual setup, run the following from the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
npm ci
Copy-Item .env.example .env
```

If PowerShell blocks virtual-environment activation, enable locally signed scripts for the
current user and open a new terminal:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

Start the API and web app in separate PowerShell windows:

```powershell
.\.venv\Scripts\Activate.ps1
python -m alembic -c apps/api/alembic.ini upgrade head
python -m uvicorn app.main:app --reload --env-file .env --app-dir apps/api --host 127.0.0.1 --port 8000
```

```powershell
npm run dev --workspace @logan/web
```

## macOS

From the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
npm ci
cp .env.example .env
```

Start the API and web app in separate terminals:

```bash
source .venv/bin/activate
python -m alembic -c apps/api/alembic.ini upgrade head
python -m uvicorn app.main:app --reload --env-file .env --app-dir apps/api --host 127.0.0.1 --port 8000
```

```bash
npm run dev --workspace @logan/web
```

Open `http://localhost:3000`. With an empty `LOGAN_SSO_AUTHORIZE_URL`, development creates a
session for the local default user. To enable SSO, set:

```text
LOGAN_SSO_AUTHORIZE_URL=https://sso.example.com/oauth2/authorize
LOGAN_SSO_TOKEN_URL=https://sso.example.com/oauth2/token
LOGAN_SSO_CLIENT_ID=logan
```

The login page then redirects to the configured SSO provider. Production requires all three
settings.

## Docker Compose

Create `.env` first, then run:

```bash
docker compose up --build
```

Compose applies pending database migrations, starts the two applications, and stores the SQLite
database and uploaded files in the `logan-data` volume. `NEXT_PUBLIC_API_BASE_URL` is a web build
argument, so rebuild the web image after changing it.

## AI providers

No AI configuration is required to start. Runs without a provider use the deterministic
processing pipeline. To enable template annotation, generated summary text, and analysis chat,
open **AI Providers** in the web app and add a provider:

- **AI Platform**: enter the chat host (or accept the deployment default), then either a trust
  token or iB2B username, password, and usercase.
- **GitHub Copilot**: save the provider, choose **Connect GitHub**, and confirm the one-time code
  on github.com. You can also paste an existing GitHub token.

Each provider lists the models it offers and a default thinking level; both can be changed per
run and per chat question. Deployments can pre-fill the AI Platform endpoints with the
`LOGAN_AI_PLATFORM_*` settings in `.env.full.example`.

## Validation

Run the checks from the repository root:

```bash
python -m ruff check apps tests scripts
python -m pytest -q
npm run lint
npm run typecheck
npm run build
```

After changing API routes or schemas, refresh the checked-in contract:

```bash
python scripts/export_openapi.py --out docs/openapi.snapshot.json
```

## Troubleshooting

### SSO redirects to the wrong address

Set `LOGAN_WEB_BASE_URL` to the browser-visible web origin. Confirm that the SSO application
has the API callback URL and that `LOGAN_SSO_AUTHORIZE_URL`, `LOGAN_SSO_TOKEN_URL`, and
`LOGAN_SSO_CLIENT_ID` are correct.

### The browser receives an authentication or CORS error

Open the local web application at `http://localhost:3000`. Development mode also accepts
`http://127.0.0.1:3000`; when configuring the origins explicitly, use:

```text
LOGAN_CORS_ALLOWED_ORIGINS=http://localhost:3000,http://127.0.0.1:3000
```

The web app sends API requests directly to `NEXT_PUBLIC_API_BASE_URL` with the session cookie.
Keep `LOGAN_WEB_BASE_URL`, the browser URL, and the API host consistent.

### The development WebSocket disconnects

Confirm that the web terminal opened by `scripts\local.bat` is still running. Stop any existing
process on port 3000, close stale browser tabs, run the launcher again, and open
`http://localhost:3000`. The launcher refuses to start when ports 3000 or 8000 are already in use.

### An AI provider test fails

Use **Test connection** on the provider card. An AI Platform provider needs a reachable chat host
plus a trust token or complete iB2B credentials (username, password, usercase, iB2B host, and
URI). A GitHub Copilot provider must be connected through **Connect GitHub**; a `401` from the
token exchange means the GitHub authorization expired and must be repeated.

### Provider TLS verification fails

Keep TLS verification enabled. Set `LOGAN_AI_PLATFORM_CA_BUNDLE` or
`LOGAN_GITHUB_COPILOT_CA_BUNDLE` to the corporate CA bundle when traffic passes an internal
certificate chain. Proxy and timeout settings are available in `.env.full.example`.

### Stored provider credentials stop working after a redeploy

Provider credentials are encrypted with a key derived from `LOGAN_SECRET_KEY`. Keep the secret
stable across restarts; after a rotation, users must re-enter credentials or reconnect GitHub.

### A file cannot be uploaded

Each file must contain at least one byte and is limited to 300 MiB by default. Set
`LOGAN_MAX_UPLOAD_BYTES` to a positive byte count to change the limit. The same configured limit
applies to the combined expanded content of a zip, gzip, tar, or tgz input.

### The web application reports that `next` is not recognized

Run `scripts\local.bat` without `-SkipInstall`. The launcher verifies the web workspace
dependencies and installs them with `npm ci` when they are missing or incomplete. If installation
still fails, run `npm ci` from the repository root and resolve the reported npm error before
starting the launcher again.
