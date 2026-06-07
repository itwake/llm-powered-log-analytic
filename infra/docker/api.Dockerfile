FROM mirror.gcr.io/library/python:3.12-slim

WORKDIR /app
COPY pyproject.toml README.md ./
COPY apps/api ./apps/api
COPY apps/workers ./apps/workers
RUN pip install --no-cache-dir -e .
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--app-dir", "apps/api", "--host", "0.0.0.0", "--port", "8000"]
