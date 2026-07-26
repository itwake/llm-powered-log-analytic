COMPOSE ?= docker compose
PYTHON ?= python3
NPM ?= npm

.PHONY: setup up down migrate test lint check api web openapi

setup:
	$(PYTHON) -m pip install -e ".[dev]"
	$(NPM) ci

up:
	$(COMPOSE) up --build

down:
	$(COMPOSE) down

migrate:
	$(PYTHON) scripts/run_migrations.py

test:
	$(PYTHON) -m pytest -q

lint:
	$(PYTHON) -m ruff check apps tests scripts
	$(NPM) run lint

check: lint test

api:
	$(PYTHON) -m uvicorn app.main:app --reload --app-dir apps/api --host 127.0.0.1 --port 8000

web:
	$(NPM) run dev --workspace @logan/web

openapi:
	$(PYTHON) scripts/export_openapi.py --out docs/openapi.snapshot.json
