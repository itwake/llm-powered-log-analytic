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

## LLM mode

The default configuration uses:

```text
LOGAN_LLM_PROVIDER=none
```

This runs the deterministic processing pipeline without model calls. AI annotation, generated
summary text, and analysis chat require:

```text
LOGAN_LLM_PROVIDER=ai_platform
```

AI Platform mode also requires a chat host and either a token or a complete set of iB2B
credentials. Copy `.env.full.example` when every supported setting and its default value is
needed.

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

### AI Platform configuration is rejected at startup

For `ai_platform`, configure `LOGAN_AI_PLATFORM_CHAT_HOST` and either
`LOGAN_AI_PLATFORM_TOKEN` or all iB2B host, URI, username, password, and usercase settings.

### AI Platform TLS verification fails

Keep TLS verification enabled. Set `LOGAN_AI_PLATFORM_CA_BUNDLE` to the corporate CA bundle
when the platform uses an internal certificate chain. Proxy and timeout settings are available
in `.env.full.example`.

### A file cannot be uploaded

Each file must contain at least one byte and be no larger than 100 MiB. The combined expanded
content of a zip, gzip, tar, or tgz input must also be no larger than 100 MiB.

### The web application reports that `next` is not recognized

Run `scripts\local.bat` without `-SkipInstall`. The launcher verifies the web workspace
dependencies and installs them with `npm ci` when they are missing or incomplete. If installation
still fails, run `npm ci` from the repository root and resolve the reported npm error before
starting the launcher again.
