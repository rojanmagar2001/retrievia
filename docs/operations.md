# Operations Guide

## Health and Readiness

- Liveness: `GET /healthz`
- Readiness: `GET /readyz`

Example:

```bash
curl -s http://localhost:8000/healthz
curl -s http://localhost:8000/readyz
```

## Logs

Application logs are structured JSON when `LOG_JSON=true`.

Run locally:

```bash
make dev
```

Run with Docker:

```bash
make logs
make api
make worker
```

## Infra Operations

Local infra (Homebrew):

```bash
make infra-local-up
make infra-local-down
```

Docker infra only:

```bash
make infra-up
make infra-restart
make infra-logs
make infra-down
```

## Incident Quick Checks

1. API process up and listening on `:8000`
2. Redis reachable (`localhost:6379` locally)
3. Postgres reachable (`localhost:5432` locally)
4. Required env vars set in `.env`

## Security Basics for Ops

- Rotate JWT secret before non-local deployments.
- Store provider keys in secret manager, not in git.
- Keep `.env` local and untracked.
