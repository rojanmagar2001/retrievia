SHELL := /bin/bash

PYTHON ?= python3.14
VENV ?= .venv
BIN := $(VENV)/bin

.PHONY: help setup venv install install-dev bootstrap dev run-api run-worker run-api-dev run-worker-dev local-services-up local-services-down infra-up infra-down infra-restart infra-logs infra-ps infra-local-up infra-local-down db-upgrade db-downgrade db-current db-migrate seed-auth-test seed-rag-test lint format test typecheck lint-local format-local test-local typecheck-local lint-docker format-docker test-docker build up down restart logs ps api worker api-shell worker-shell

help:
	@printf "Local setup:\n"
	@printf "  setup              Copy .env.example to .env if missing\n"
	@printf "  venv               Create virtualenv with $(PYTHON)\n"
	@printf "  install            Install app dependencies\n"
	@printf "  install-dev        Install app + dev dependencies\n"
	@printf "  bootstrap          setup + venv + install-dev\n\n"
	@printf "Run locally:\n"
	@printf "  dev                Run API + worker together (single terminal)\n"
	@printf "  run-api            Run FastAPI on port 8000\n"
	@printf "  run-worker         Run Celery worker\n"
	@printf "  run-api-dev        Alias for run-api\n"
	@printf "  run-worker-dev     Alias for run-worker\n"
	@printf "  local-services-up  Start local Postgres + Redis (Homebrew)\n"
	@printf "  local-services-down Stop local Postgres + Redis (Homebrew)\n\n"
	@printf "Infra only:\n"
	@printf "  infra-up           Start only Postgres + Redis (Docker)\n"
	@printf "  infra-down         Stop only Postgres + Redis (Docker)\n"
	@printf "  infra-restart      Restart only Postgres + Redis (Docker)\n"
	@printf "  infra-logs         Tail only Postgres + Redis logs (Docker)\n"
	@printf "  infra-ps           Show only Postgres + Redis status (Docker)\n"
	@printf "  infra-local-up     Start only Postgres + Redis (Homebrew)\n"
	@printf "  infra-local-down   Stop only Postgres + Redis (Homebrew)\n\n"
	@printf "Quality checks (local):\n"
	@printf "  lint               Ruff check app/\n"
	@printf "  format             Ruff format app/\n"
	@printf "  test               Pytest\n"
	@printf "  typecheck          Mypy app/\n\n"
	@printf "Database (future-ready):\n"
	@printf "  db-upgrade         Alembic upgrade head\n"
	@printf "  db-downgrade       Alembic downgrade -1\n"
	@printf "  db-current         Alembic current revision\n"
	@printf "  db-migrate         Run scripts/db_migrate.py (ACTION, REVISION)\n\n"
	@printf "  seed-auth-test     Seed test tenants/users\n\n"
	@printf "  seed-rag-test      Seed tenant docs + conversations for RAG tests\n\n"
	@printf "Docker workflow:\n"
	@printf "  build              Build api/worker images\n"
	@printf "  up                 Start all docker services\n"
	@printf "  down               Stop and remove docker services\n"
	@printf "  restart            Restart docker services\n"
	@printf "  logs               Tail docker logs\n"
	@printf "  ps                 Show docker service status\n"
	@printf "  api                Tail docker API logs\n"
	@printf "  worker             Tail docker worker logs\n"
	@printf "  api-shell          Shell into docker api container\n"
	@printf "  worker-shell       Shell into docker worker container\n"
	@printf "  lint-docker        Ruff check in docker api container\n"
	@printf "  format-docker      Ruff format in docker api container\n"
	@printf "  test-docker        Pytest in docker api container\n"

setup:
	@test -f .env || cp .env.example .env
	@printf ".env ready\n"

venv:
	$(PYTHON) -m venv $(VENV)

install:
	$(BIN)/python -m pip install --upgrade pip
	$(BIN)/pip install -e .

install-dev:
	$(BIN)/python -m pip install --upgrade pip
	$(BIN)/pip install -e ".[dev]"

bootstrap: setup venv install-dev

dev:
	@bash -c 'set -euo pipefail; \
	cleanup() { \
	  trap - INT TERM EXIT; \
	  if [ -n "$${API_PID:-}" ]; then kill "$$API_PID" 2>/dev/null || true; fi; \
	  if [ -n "$${WORKER_PID:-}" ]; then kill "$$WORKER_PID" 2>/dev/null || true; fi; \
	  wait 2>/dev/null || true; \
	}; \
	trap cleanup INT TERM EXIT; \
	$(BIN)/uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload & API_PID=$$!; \
	REDIS_URL=redis://localhost:6379/0 CELERY_BROKER_URL=redis://localhost:6379/1 CELERY_RESULT_BACKEND=redis://localhost:6379/2 $(BIN)/celery -A app.worker.celery_app.celery_app worker --loglevel=INFO --concurrency=2 & WORKER_PID=$$!; \
	STATUS=0; \
	while kill -0 $$API_PID 2>/dev/null && kill -0 $$WORKER_PID 2>/dev/null; do sleep 1; done; \
	if ! kill -0 $$API_PID 2>/dev/null; then \
	  wait $$API_PID || STATUS=$$?; \
	else \
	  wait $$WORKER_PID || STATUS=$$?; \
	fi; \
	exit $$STATUS'

run-api:
	$(BIN)/uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

run-worker:
	REDIS_URL=redis://localhost:6379/0 CELERY_BROKER_URL=redis://localhost:6379/1 CELERY_RESULT_BACKEND=redis://localhost:6379/2 $(BIN)/celery -A app.worker.celery_app.celery_app worker --loglevel=INFO --concurrency=2

run-api-dev: run-api

run-worker-dev: run-worker

local-services-up:
	brew services start postgresql@16
	brew services start redis

local-services-down:
	brew services stop postgresql@16
	brew services stop redis

infra-up:
	docker compose up -d postgres redis

infra-down:
	docker compose stop postgres redis

infra-restart:
	docker compose restart postgres redis

infra-logs:
	docker compose logs -f postgres redis

infra-ps:
	docker compose ps postgres redis

infra-local-up: local-services-up

infra-local-down: local-services-down

db-upgrade:
	DATABASE_URL=$${DATABASE_URL:-postgresql+psycopg://retrievia:retrievia@localhost:5432/retrievia} $(BIN)/alembic upgrade head

db-downgrade:
	DATABASE_URL=$${DATABASE_URL:-postgresql+psycopg://retrievia:retrievia@localhost:5432/retrievia} $(BIN)/alembic downgrade -1

db-current:
	DATABASE_URL=$${DATABASE_URL:-postgresql+psycopg://retrievia:retrievia@localhost:5432/retrievia} $(BIN)/alembic current

db-migrate:
	@test -n "$(ACTION)" || (printf "Usage: make db-migrate ACTION=<upgrade|downgrade|current> [REVISION=<rev>]\n" && exit 1)
	@if [ -n "$(REVISION)" ]; then \
		DATABASE_URL=$${DATABASE_URL:-postgresql+psycopg://retrievia:retrievia@localhost:5432/retrievia} $(BIN)/python scripts/db_migrate.py $(ACTION) $(REVISION); \
	else \
		DATABASE_URL=$${DATABASE_URL:-postgresql+psycopg://retrievia:retrievia@localhost:5432/retrievia} $(BIN)/python scripts/db_migrate.py $(ACTION); \
	fi

seed-auth-test:
	DATABASE_URL=$${DATABASE_URL:-postgresql+psycopg://retrievia:retrievia@localhost:5432/retrievia} $(BIN)/python scripts/seed_test_auth_data.py

seed-rag-test:
	DATABASE_URL=$${DATABASE_URL:-postgresql+psycopg://retrievia:retrievia@localhost:5432/retrievia} $(BIN)/python scripts/seed_test_rag_data.py

lint: lint-local

format: format-local

test: test-local

typecheck: typecheck-local

lint-local:
	$(BIN)/ruff check app

format-local:
	$(BIN)/ruff format app

test-local:
	$(BIN)/pytest -q

typecheck-local:
	$(BIN)/mypy app

build:
	docker compose build

up:
	docker compose up -d

down:
	docker compose down

restart:
	docker compose down && docker compose up -d

logs:
	docker compose logs -f

ps:
	docker compose ps

api:
	docker compose logs -f api

worker:
	docker compose logs -f worker

api-shell:
	docker compose exec api bash

worker-shell:
	docker compose exec worker bash

lint-docker:
	docker compose exec api ruff check app

test-docker:
	docker compose exec api pytest -q

format-docker:
	docker compose exec api ruff format app
