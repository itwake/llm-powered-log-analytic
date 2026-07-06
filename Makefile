COMPOSE ?= docker compose
PYTHON ?= python3
NPM ?= npm
SCALE_PROFILE ?= quick
SCALE_TARGET_BYTES ?=

.PHONY: setup up migrate test evaluate scale-benchmark e2e lint api worker web demo demo-logs quickstart-up quickstart-down full-stack-up full-stack-smoke full-stack-down temporal-retry-smoke openapi-snapshot

setup:
	$(NPM) install
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
	$(NPM) run e2e

lint:
	$(PYTHON) -m compileall apps/api apps/workers
	$(NPM) run lint --workspace @logan/web

api:
	uvicorn app.main:app --reload --app-dir apps/api --host 0.0.0.0 --port 8000

worker:
	python3 -m logan_workers.workflows.analyze_case_workflow

web:
	$(NPM) run dev --workspace @logan/web

demo:
	$(PYTHON) scripts/seed_demo_case.py --logs-dir demo/logs

demo-logs:
	$(PYTHON) scripts/generate_demo_logs.py

quickstart-up:
	$(COMPOSE) -f docker-compose.quickstart.yml up -d --build

quickstart-down:
	$(COMPOSE) -f docker-compose.quickstart.yml down --remove-orphans

full-stack-up:
	$(COMPOSE) up -d --build postgres redis minio minio-init clickhouse opensearch temporal api worker

full-stack-smoke: full-stack-up
	$(COMPOSE) --profile smoke run --rm -T --build smoke

full-stack-down:
	$(COMPOSE) down --remove-orphans

temporal-retry-smoke:
	LOGAN_RUN_TEMPORAL_INTEGRATION=true python3 -m pytest -q tests/integration/test_temporal_retry.py

openapi-snapshot:
	$(PYTHON) scripts/export_openapi.py --out docs/openapi.snapshot.json
