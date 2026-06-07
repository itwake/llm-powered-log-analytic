COMPOSE ?= docker compose
PYTHON ?= python3
SCALE_PROFILE ?= quick
SCALE_TARGET_BYTES ?=

.PHONY: setup up migrate test evaluate scale-benchmark e2e lint api worker web full-stack-up full-stack-smoke full-stack-down copilot-staging-smoke temporal-retry-smoke openapi-snapshot

setup:
	corepack enable
	corepack prepare pnpm@10.13.1 --activate
	pnpm install
	$(PYTHON) -m pip install -e .

up:
	$(COMPOSE) up --build

migrate:
	$(PYTHON) scripts/run_migrations.py

test:
	$(PYTHON) -m pytest tests

evaluate:
	$(PYTHON) -m logan_workers.evaluation.run \
		--benchmark benchmarks/logan/checkout_incident \
		--out .logan/evaluation/report.json \
		--markdown .logan/evaluation/report.md

scale-benchmark:
	$(PYTHON) -m logan_workers.evaluation.scale \
		--profile $(SCALE_PROFILE) \
		--fixture-dir .logan/scale-fixtures \
		--out .logan/evaluation/scale-$(SCALE_PROFILE).json \
		--markdown .logan/evaluation/scale-$(SCALE_PROFILE).md \
		$(if $(SCALE_TARGET_BYTES),--target-bytes $(SCALE_TARGET_BYTES),)

e2e:
	corepack pnpm e2e

lint:
	$(PYTHON) -m compileall apps/api apps/workers
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
	$(COMPOSE) --profile smoke run --rm -T --build smoke

full-stack-down:
	$(COMPOSE) down --remove-orphans

copilot-staging-smoke:
	LOGAN_RUN_COPILOT_STAGING_SMOKE=true python3 -m pytest -q tests/staging/test_copilot_smoke.py

temporal-retry-smoke:
	LOGAN_RUN_TEMPORAL_INTEGRATION=true python3 -m pytest -q tests/integration/test_temporal_retry.py

openapi-snapshot:
	$(PYTHON) scripts/export_openapi.py --out docs/openapi.snapshot.json
