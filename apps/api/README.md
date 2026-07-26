# API

The FastAPI application provides SSO sessions, cases, local uploads, background analysis, reports,
chat, and health.

Run from the repository root:

```bash
python -m uvicorn app.main:app --reload --env-file .env --app-dir apps/api
```

Key modules:

- `app/api`: HTTP routes
- `app/sqlalchemy_store.py`: application persistence
- `app/services`: SSO, AI Platform, and local file storage
- `logan_analysis`: analysis models and pipeline
