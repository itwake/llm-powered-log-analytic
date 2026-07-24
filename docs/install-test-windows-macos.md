# Install and test on Windows or macOS

Requirements:

- Python 3.11 or newer
- Node.js 22 or newer
- Git

```bash
python -m venv .venv
```

Activate it:

```powershell
# Windows PowerShell
.\.venv\Scripts\Activate.ps1
```

```bash
# macOS
source .venv/bin/activate
```

Install and test:

```bash
python -m pip install -e .
npm install
python -m pytest
npm run lint
```

Run locally with the values from `.env.example`, or use the same two-service Docker stack on both
platforms:

```bash
docker compose up -d --build
```

Playwright requires its browser once:

```bash
npm run e2e:install
npm run e2e
```

No service dependencies are required for the unit or browser test suites.
