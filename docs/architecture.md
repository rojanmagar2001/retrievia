# Architecture (Current Scaffold)

## Application Layer

- `app/main.py`
  - FastAPI app creation
  - lifespan startup/shutdown logs
  - health endpoints (`/healthz`, `/readyz`)

## Core Layer

- `app/core/config.py`
  - Pydantic Settings model for all env-backed config
  - cached settings access
- `app/core/logging.py`
  - structlog JSON logging setup

## Worker Layer

- `app/worker/celery_app.py`
  - Celery app initialization
  - JSON serializer config
  - retry-on-startup config
  - `health.ping` task placeholder

## Runtime Topologies

## Local (no Docker)

- API via `uvicorn`
- Worker via `celery`
- Postgres and Redis via Homebrew services

## Docker Compose

- `api`
- `worker`
- `postgres`
- `redis`

## Not Yet Implemented

- Domain/business modules for auth, tenancy, ingestion, retrieval, generation
- DB models and migrations
- API routers beyond health endpoints
- OTel instrumentation wiring (dependencies are present)
