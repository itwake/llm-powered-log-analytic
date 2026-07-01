# Windows and macOS Install/Test Guide

This guide is for local developer verification on Windows PowerShell and macOS
Terminal. The default path uses the deterministic `StableDrainAdapter`; do not
install the optional Drain3 extra unless your package mirror can resolve
Drain3's legacy `jsonpickle` pin.

## Common Requirements

- Git
- Python 3.11 or newer, Python 3.12 recommended
- Node.js 20.9 or newer with npm
- Docker Desktop for full-stack smoke tests

The Python unit tests do not require Docker, AI Platform credentials, MinIO,
ClickHouse, OpenSearch, Temporal, or PostgreSQL.

## Windows PowerShell

Run all commands from a normal PowerShell session unless noted otherwise.

```powershell
git clone https://github.com/itwake/llm-powered-log-analytic.git
cd llm-powered-log-analytic
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e . pytest pytest-asyncio ruff
npm install
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

If PowerShell blocks venv activation, enable script execution for the current
user and open a new shell:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

Clear environment variables that can intentionally change test behavior:

```powershell
Remove-Item Env:LOGAN_OBJECT_STORE_BACKEND -ErrorAction SilentlyContinue
Remove-Item Env:LOGAN_STEP_ARTIFACTS_ENABLED -ErrorAction SilentlyContinue
Remove-Item Env:LOGAN_DATABASE_URL -ErrorAction SilentlyContinue
Remove-Item Env:LOGAN_STORE_BACKEND -ErrorAction SilentlyContinue
Remove-Item Env:LOGAN_LLM_PROVIDER -ErrorAction SilentlyContinue
```

With those variables cleared, the API defaults to SQLite at `.logan/logan.db`
and the test suite overrides individual tests to use isolated temporary stores
where needed.

Run Python checks:

```powershell
python -m pytest -q
python -m ruff check apps tests scripts
python -m logan_workers.evaluation.run `
  --benchmark benchmarks/logan/checkout_incident `
  --out .logan/evaluation/report.json `
  --markdown .logan/evaluation/report.md
python -m logan_workers.evaluation.scale `
  --profile quick `
  --target-bytes 65536 `
  --out .logan/evaluation/scale-quick.json `
  --markdown .logan/evaluation/scale-quick.md
```

Run web checks:

```powershell
npm run build --workspace @logan/web
npm run test --workspace @logan/web
npm run e2e:install
npm run e2e
```

Run the full-stack Docker smoke from PowerShell. This is the Makefile-equivalent
path for Windows environments without `make`:

```powershell
docker compose config
docker compose up -d --build postgres redis minio minio-init clickhouse opensearch temporal api worker
docker compose --profile smoke run --rm -T --build smoke
docker compose down --remove-orphans -v
```

If you use Git Bash, MSYS2, Chocolatey, or WSL and have `make`, this is
equivalent:

```powershell
make full-stack-smoke
make full-stack-down
```

## macOS Terminal

Install prerequisites with Homebrew if they are not already present:

```bash
xcode-select --install || true
brew install python@3.12 node git
```

Install and test from a fresh shell:

```bash
git clone https://github.com/itwake/llm-powered-log-analytic.git
cd llm-powered-log-analytic
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e . pytest pytest-asyncio ruff
npm install
cp -n .env.example .env
```

Clear environment variables that can intentionally change test behavior:

```bash
unset LOGAN_OBJECT_STORE_BACKEND
unset LOGAN_STEP_ARTIFACTS_ENABLED
unset LOGAN_DATABASE_URL
unset LOGAN_STORE_BACKEND
unset LOGAN_LLM_PROVIDER
```

With those variables cleared, the API defaults to SQLite at `.logan/logan.db`
and the test suite overrides individual tests to use isolated temporary stores
where needed.

Run Python checks:

```bash
python -m pytest -q
python -m ruff check apps tests scripts
python -m logan_workers.evaluation.run \
  --benchmark benchmarks/logan/checkout_incident \
  --out .logan/evaluation/report.json \
  --markdown .logan/evaluation/report.md
python -m logan_workers.evaluation.scale \
  --profile quick \
  --target-bytes 65536 \
  --out .logan/evaluation/scale-quick.json \
  --markdown .logan/evaluation/scale-quick.md
```

Run web checks:

```bash
npm run build --workspace @logan/web
npm run test --workspace @logan/web
npm run e2e:install
npm run e2e
```

Run the full-stack Docker smoke after starting Docker Desktop:

```bash
docker compose config
make full-stack-smoke
make full-stack-down
```

If `make` is unavailable, use the direct compose commands:

```bash
docker compose up -d --build postgres redis minio minio-init clickhouse opensearch temporal api worker
docker compose --profile smoke run --rm -T --build smoke
docker compose down --remove-orphans -v
```

## Troubleshooting

- `jsonpickle==1.5.1` cannot be resolved: use the default install
  `python -m pip install -e .`. Do not install `.[drain3]` unless your mirror
  publishes Drain3's legacy dependency set.
- `resource` is missing on Windows: supported. Scale reports leave peak RSS as
  `null` on platforms without the Unix `resource` module.
- Step artifact path errors on Windows: pull the latest `master`; local step
  manifests use short hashed paths under `.logan/object-store/step-artifacts/`.
- Playwright cannot find Chromium: rerun `npm run e2e:install`.
- AI Platform calls fail with `CERTIFICATE_VERIFY_FAILED`: export your corporate
  root CA chain as a PEM file and set `LOGAN_AI_PLATFORM_CA_BUNDLE` to that path
  before starting the API. `SSL_CERT_FILE` and `REQUESTS_CA_BUNDLE` are also
  honored when `LOGAN_AI_PLATFORM_CA_BUNDLE` is not set.
- AI Platform calls fail with `ReadTimeout`: make sure the API process inherits
  `HTTPS_PROXY`, `HTTP_PROXY`, `ALL_PROXY`, and `NO_PROXY`, or set
  `LOGAN_AI_PLATFORM_PROXY_URL` explicitly. Increase `LOGAN_AI_PLATFORM_TIMEOUT_SECONDS`
  for slow enterprise proxies. On Windows, restart PowerShell after changing
  System Properties or `setx`, then verify with
  `python -c "import os; print(os.getenv('HTTPS_PROXY'))"`.
- Docker smoke times out: allocate at least 6 GiB memory to Docker Desktop and
  run `docker compose down --remove-orphans -v` before retrying.
- Existing local services on ports 3000 or 8000 can affect E2E reuse behavior.
  Stop them or ensure they use the same E2E settings, including
  `LOGAN_STORE_BACKEND=memory` and `LOGAN_LLM_PROVIDER=mock`.
