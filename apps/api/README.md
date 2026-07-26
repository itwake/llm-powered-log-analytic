# API

The FastAPI application provides SSO sessions, cases, local uploads, background analysis, reports,
chat, health, and metrics.

Run from the repository root:

```bash
python -m uvicorn app.main:app --reload --app-dir apps/api
```

Key modules:

- `app/api`: HTTP routes
- `app/sqlalchemy_store.py`: application persistence
- `app/services`: SSO, AI Platform, and local file storage
- `logan_analysis`: analysis models and pipeline
- `migrations/0001_initial.sql`: PostgreSQL schema
