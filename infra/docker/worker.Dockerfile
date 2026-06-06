FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml README.md ./
COPY apps/workers ./apps/workers
RUN pip install --no-cache-dir -e .
CMD ["python", "-m", "logan_workers.workflows.analyze_case_workflow"]
