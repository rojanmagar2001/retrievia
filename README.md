# Retrievia

Production-grade backend scaffold for a multi-tenant RAG chatbot built with FastAPI, Celery, Postgres, Redis, Pinecone, and Gemini.

## Current Status

This repository currently includes infrastructure and application bootstrapping:

- FastAPI app skeleton with `/healthz` and `/readyz`
- Pydantic Settings-based configuration management
- Structured logging setup (JSON logs)
- Celery worker scaffold
- Local development workflows via Makefile
- Docker Compose setup for API, worker, Postgres, and Redis

Business logic (RAG ingestion/retrieval/generation flows) is intentionally not implemented yet.

## Documentation

- Documentation index: `docs/README.md`
- Getting started: `docs/getting-started.md`
- Configuration: `docs/configuration.md`
- Development workflow: `docs/development.md`
- Architecture: `docs/architecture.md`
- Operations: `docs/operations.md`

## Tech Stack

- Python 3.14
- FastAPI
- Celery + Redis
- PostgreSQL
- Pinecone
- Google Gemini (`google-genai`)
- OpenTelemetry (hooks/dependencies present)

## Project Layout

```text
.
├── app/
│   ├── core/
│   │   ├── config.py
│   │   └── logging.py
│   ├── worker/
│   │   └── celery_app.py
│   └── main.py
├── docker/
│   ├── api.Dockerfile
│   └── worker.Dockerfile
├── docker-compose.yml
├── Makefile
├── pyproject.toml
└── .env.example
```

## Prerequisites

- Python 3.14
- Homebrew services (for local Postgres/Redis), optional but recommended on macOS
- Docker Desktop (optional, if using docker-based workflow)

## Environment Setup

Copy and customize environment variables:

```bash
cp .env.example .env
```

Minimum keys to set for future provider usage:

- `GEMINI_API_KEY`
- `PINECONE_API_KEY`
- `PINECONE_INDEX_NAME`
- `JWT_SECRET_KEY` (replace with a long random secret)

## Local Development (Without Docker)

1) Bootstrap the project:

```bash
make bootstrap
```

2) Start local infrastructure (Postgres + Redis):

```bash
make infra-local-up
```

3) Run API + worker together:

```bash
make dev
```

Or run them separately:

```bash
make run-api
# new terminal
make run-worker
```

4) Stop local infra when done:

```bash
make infra-local-down
```

## Docker Workflow

Build and run all services:

```bash
make build
make up
```

Infrastructure-only docker services:

```bash
make infra-up
```

Useful logs:

```bash
make logs
make api
make worker
make infra-logs
```

## Quality Commands

Local:

```bash
make lint
make format
make test
make typecheck
```

Docker-based:

```bash
make lint-docker
make format-docker
make test-docker
```

## API Endpoints (Current)

- `GET /healthz` -> liveness check
- `GET /readyz` -> readiness check

## Notes

- The scaffold is intentionally strict about environment-driven configuration.
- Defaults in `.env.example` are for development only.
- Do not commit real secrets in `.env`.
