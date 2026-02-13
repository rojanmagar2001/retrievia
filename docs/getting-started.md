# Getting Started

## Prerequisites

- Python `3.14`
- macOS + Homebrew (for local Postgres/Redis) or Docker Desktop

## 1) Clone and configure

```bash
cp .env.example .env
```

Set at least:

- `JWT_SECRET_KEY`
- `GEMINI_API_KEY`
- `PINECONE_API_KEY`
- `PINECONE_INDEX_NAME`

## 2) Bootstrap local environment

```bash
make bootstrap
```

This runs:

- `setup` (`.env` creation if missing)
- `venv` (creates `.venv`)
- `install-dev` (installs app + dev dependencies)

## 3) Start local infrastructure

```bash
make infra-local-up
```

## 4) Run app + worker

```bash
make dev
```

Or separately:

```bash
make run-api
make run-worker
```

## 5) Verify service

```bash
curl http://localhost:8000/healthz
curl http://localhost:8000/readyz
```

## Optional: Docker workflow

```bash
make build
make up
make ps
```
