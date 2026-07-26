# Getting started

This guide covers local installation on Windows and macOS. LogAn runs two applications:
the FastAPI API on port 8000 and the Next.js web app on port 3000.

## Requirements

- Git
- Python 3.11 or newer
- Node.js 22 or newer with npm
- An OAuth-compatible SSO application
- Docker Desktop only when using Docker Compose

Configure the SSO application to allow this callback URL for local development:

```text
http://localhost:8000/api/auth/sso/callback
```

## Windows PowerShell

From the repository root:

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

Edit `.env` with the SSO authorize URL, token URL, and client id. Start the API and web app
in separate PowerShell windows:

```powershell
.\.venv\Scripts\Activate.ps1
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

Edit `.env` with the SSO authorize URL, token URL, and client id. Start the API and web app
in separate terminals:

```bash
source .venv/bin/activate
python -m uvicorn app.main:app --reload --env-file .env --app-dir apps/api --host 127.0.0.1 --port 8000
```

```bash
npm run dev --workspace @logan/web
```

Open `http://localhost:3000`. The login page redirects to the configured SSO provider.

## Docker Compose

Create `.env` first, then run:

```bash
docker compose up --build
```

Compose starts the same two applications and stores the SQLite database and uploaded files
in the `logan-data` volume. `NEXT_PUBLIC_API_BASE_URL` is a web build argument, so rebuild
the web image after changing it.

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

Set `LOGAN_CORS_ALLOWED_ORIGINS` to the exact web origin, including scheme and port. The web
app sends API requests directly to `NEXT_PUBLIC_API_BASE_URL` with the session cookie.

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
