# Contributing

Create a branch, keep changes scoped, and update code, tests, configuration examples, and
documentation together.

Before opening a pull request, run:

```bash
python -m ruff check apps tests scripts
python -m pytest -q
npm run typecheck
npm run build
```

API changes must include a refreshed `docs/openapi.snapshot.json`.

Do not commit `.env`, `.logan/`, access tokens, SSO responses, raw customer logs, or model
credentials. Test fixtures must be synthetic and contain no sensitive data.
