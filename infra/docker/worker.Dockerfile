FROM mirror.gcr.io/library/python:3.12-slim

WORKDIR /app
COPY pyproject.toml README.md ./
COPY apps/api ./apps/api
COPY apps/workers ./apps/workers
RUN pip install --no-cache-dir .
CMD ["python", "-m", "logan_workers.temporal_worker"]
