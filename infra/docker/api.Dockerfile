FROM python:3.12-slim

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY pyproject.toml README.md ./
COPY apps/api ./apps/api
RUN python -m pip install --no-cache-dir .

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2).read()"
CMD ["sh", "-c", "python -m alembic -c apps/api/alembic.ini upgrade head && exec python -m uvicorn app.main:app --app-dir apps/api --host 0.0.0.0 --port 8000"]
