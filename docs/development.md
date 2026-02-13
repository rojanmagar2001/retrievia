# Development Workflow

## Common Commands

```bash
make help
make bootstrap
make dev
```

## Local Infra

```bash
make infra-local-up
make infra-local-down
```

## Docker Infra / Full Stack

```bash
make infra-up
make infra-logs
make up
make logs
make down
```

## Code Quality

```bash
make lint
make format
make test
make typecheck
```

## Troubleshooting

## Celery cannot connect to Redis

- Ensure Redis is running (`make infra-local-up`).
- Current local worker targets force Redis localhost URLs for local execution.

## API startup errors

- Check env values in `.env`.
- Run `source .venv/bin/activate` and retry.
- Validate imports with:

```bash
python -c "from app.main import app; print(app.title)"
```

## Python version mismatch

- Project targets Python `3.14`.
- Recreate venv if needed:

```bash
rm -rf .venv
make venv
make install-dev
```
