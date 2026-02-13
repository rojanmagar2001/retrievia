from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "retrievia-api"
    app_env: Literal["development", "staging", "production", "test"] = "development"
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    log_level: str = "INFO"
    log_json: bool = True
    log_include_timestamp: bool = True
    metrics_enabled: bool = True

    postgres_user: str = "retrievia"
    postgres_password: str = "retrievia"
    postgres_db: str = "retrievia"
    postgres_host: str = "postgres"
    postgres_port: int = 5432
    database_url: str = "postgresql+psycopg://retrievia:retrievia@postgres:5432/retrievia"
    async_database_url: str = "postgresql+asyncpg://retrievia:retrievia@postgres:5432/retrievia"
    db_pool_size: int = 10
    db_max_overflow: int = 20

    redis_host: str = "redis"
    redis_port: int = 6379
    redis_url: str = "redis://redis:6379/0"
    celery_broker_url: str = "redis://redis:6379/1"
    celery_result_backend: str = "redis://redis:6379/2"
    worker_concurrency: int = 2

    jwt_secret_key: str = "CHANGE_ME_WITH_A_LONG_RANDOM_SECRET"
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 15
    jwt_refresh_token_expire_minutes: int = 10080
    jwt_issuer: str = "retrievia"
    jwt_audience: str = "retrievia-clients"

    rate_limit_enabled: bool = True
    rate_limit_requests: int = 60
    rate_limit_window_seconds: int = 60

    pinecone_api_key: str = ""
    pinecone_index_name: str = ""
    pinecone_cloud: str = "aws"
    pinecone_region: str = "us-east-1"
    pinecone_namespace_prefix: str = "tenant"

    gemini_api_key: str = ""
    gemini_model: str = "gemini-1.5-pro"
    gemini_embedding_model: str = "text-embedding-004"
    gemini_timeout_seconds: int = 30

    tracing_enabled: bool = False
    otel_enabled: bool = False
    otel_service_name: str = "retrievia-api"
    otel_exporter_otlp_endpoint: str = "http://localhost:4317"
    otel_traces_sampler: str = "parentbased_traceidratio"
    otel_traces_sampler_arg: str = "1.0"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
