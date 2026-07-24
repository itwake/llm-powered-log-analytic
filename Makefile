COMPOSE ?= docker compose
PYTHON ?= python3
NPM ?= npm
SCALE_PROFILE ?= quick
SCALE_TARGET_BYTES ?=

.PHONY: setup up down migrate test evaluate scale-benchmark e2e lint check api web demo demo-logs openapi-snapshot

setup:
	$(NPM) ci
	$(PYTHON) -m pip install -e ".[dev]"

up:
	$(COMPOSE) up -d --build

down:
	$(COMPOSE) down --remove-orphans

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
	$(PYTHON) -m ruff check --select F apps tests scripts
	$(NPM) run lint --workspace @logan/web

check: lint test

api:
	$(PYTHON) -m uvicorn app.main:app --reload --app-dir apps/api --host 0.0.0.0 --port 8000

web:
	$(NPM) run dev --workspace @logan/web

demo:
	$(PYTHON) scripts/seed_demo_case.py --logs-dir demo/logs

demo-logs:
	$(PYTHON) scripts/generate_demo_logs.py

openapi-snapshot:
	$(PYTHON) scripts/export_openapi.py --out docs/openapi.snapshot.json
