.PHONY: setup up migrate test e2e lint api worker web

setup:
	corepack enable
	corepack prepare pnpm@10.13.1 --activate
	pnpm install
	python3 -m pip install -e .

up:
	docker compose up --build

migrate:
	cd apps/api && alembic upgrade head

test:
	python3 -m pytest tests

e2e:
	pnpm --filter @logan/web playwright test

lint:
	python3 -m compileall apps/api apps/workers
	pnpm --filter @logan/web lint

api:
	uvicorn app.main:app --reload --app-dir apps/api --host 0.0.0.0 --port 8000

worker:
	python3 -m logan_workers.workflows.analyze_case_workflow

web:
	pnpm --filter @logan/web dev
