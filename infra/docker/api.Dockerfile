FROM mirror.gcr.io/library/python:3.12-slim

WORKDIR /app
COPY pyproject.toml README.md ./
COPY apps/api ./apps/api
COPY apps/workers ./apps/workers
RUN pip install --no-cache-dir .
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2).read()"
CMD ["sh", "-c", "uvicorn app.main:app --app-dir apps/api --host 0.0.0.0 --port 8000 --workers ${LOGAN_API_WORKERS:-1}"]
