COMPOSE ?= docker compose

.PHONY: setup up migrate test e2e lint api worker web full-stack-up full-stack-smoke full-stack-down copilot-staging-smoke temporal-retry-smoke

setup:
	corepack enable
	corepack prepare pnpm@10.13.1 --activate
	pnpm install
	python3 -m pip install -e .

up:
	$(COMPOSE) up --build

migrate:
	cd apps/api && alembic upgrade head

test:
	python3 -m pytest tests

e2e:
	corepack pnpm e2e

lint:
	python3 -m compileall apps/api apps/workers
	pnpm --filter @logan/web lint

api:
	uvicorn app.main:app --reload --app-dir apps/api --host 0.0.0.0 --port 8000

worker:
	python3 -m logan_workers.workflows.analyze_case_workflow

web:
	pnpm --filter @logan/web dev

full-stack-up:
	$(COMPOSE) up -d --build postgres redis minio minio-init clickhouse opensearch temporal api worker

full-stack-smoke: full-stack-up
	$(COMPOSE) run --rm --build smoke

full-stack-down:
	$(COMPOSE) down --remove-orphans

copilot-staging-smoke:
	LOGAN_RUN_COPILOT_STAGING_SMOKE=true python3 -m pytest -q tests/staging/test_copilot_smoke.py

temporal-retry-smoke:
	LOGAN_RUN_TEMPORAL_INTEGRATION=true python3 -m pytest -q tests/integration/test_temporal_retry.py
