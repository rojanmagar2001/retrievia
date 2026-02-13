# Configuration

Configuration is managed with Pydantic Settings in `app/core/config.py`.

- Source order is environment-driven (with `.env` support).
- Unknown env vars are ignored (`extra="ignore"`).
- A cached singleton settings object is exposed as `settings`.

## Variable Groups

## App

- `APP_NAME`
- `APP_ENV` (`development|staging|production|test`)
- `API_HOST`
- `API_PORT`

## Logging

- `LOG_LEVEL`
- `LOG_JSON`
- `LOG_INCLUDE_TIMESTAMP`

## Postgres

- `POSTGRES_USER`
- `POSTGRES_PASSWORD`
- `POSTGRES_DB`
- `POSTGRES_HOST`
- `POSTGRES_PORT`
- `DATABASE_URL`
- `ASYNC_DATABASE_URL`
- `DB_POOL_SIZE`
- `DB_MAX_OVERFLOW`

## Redis / Worker

- `REDIS_HOST`
- `REDIS_PORT`
- `REDIS_URL`
- `CELERY_BROKER_URL`
- `CELERY_RESULT_BACKEND`
- `WORKER_CONCURRENCY`

## JWT / Security

- `JWT_SECRET_KEY`
- `JWT_ALGORITHM`
- `JWT_ACCESS_TOKEN_EXPIRE_MINUTES`
- `JWT_REFRESH_TOKEN_EXPIRE_MINUTES`
- `JWT_ISSUER`
- `JWT_AUDIENCE`

## Rate Limit

- `RATE_LIMIT_ENABLED`
- `RATE_LIMIT_REQUESTS`
- `RATE_LIMIT_WINDOW_SECONDS`

## Pinecone

- `PINECONE_API_KEY`
- `PINECONE_INDEX_NAME`
- `PINECONE_CLOUD`
- `PINECONE_REGION`
- `PINECONE_NAMESPACE_PREFIX`

## Gemini

- `GEMINI_API_KEY`
- `GEMINI_MODEL`
- `GEMINI_EMBEDDING_MODEL`
- `GEMINI_TIMEOUT_SECONDS`

## Tracing / OTel

- `TRACING_ENABLED`
- `OTEL_ENABLED`
- `OTEL_SERVICE_NAME`
- `OTEL_EXPORTER_OTLP_ENDPOINT`
- `OTEL_TRACES_SAMPLER`
- `OTEL_TRACES_SAMPLER_ARG`

## Metrics

- `METRICS_ENABLED`

## Security Notes

- Do not commit `.env` with real keys.
- Use a long random `JWT_SECRET_KEY` in all non-local environments.
- Prefer secret managers in staging/production.
