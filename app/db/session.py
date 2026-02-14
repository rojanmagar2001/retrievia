from collections.abc import Generator
from contextvars import ContextVar, Token
from uuid import UUID

from sqlalchemy import create_engine
from sqlalchemy import event
from sqlalchemy.orm import Session, sessionmaker, with_loader_criteria

from app.core.config import settings
from app.db.base import Base
from app.db.mixins import TenantScoped

engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
)

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False, class_=Session)

_tenant_context: ContextVar[UUID | None] = ContextVar("tenant_id", default=None)


def set_current_tenant_id(tenant_id: UUID) -> Token[UUID | None]:
    return _tenant_context.set(tenant_id)


def reset_current_tenant_id(token: Token[UUID | None]) -> None:
    _tenant_context.reset(token)


def get_current_tenant_id() -> UUID | None:
    return _tenant_context.get()


@event.listens_for(SessionLocal, "do_orm_execute")
def _enforce_tenant_scope(execute_state) -> None:
    tenant_id = get_current_tenant_id()
    if tenant_id is None:
        return
    if not (execute_state.is_select or execute_state.is_update or execute_state.is_delete):
        return

    statement = execute_state.statement
    for mapper in Base.registry.mappers:
        model_class = mapper.class_
        if not issubclass(model_class, TenantScoped):
            continue
        if not hasattr(model_class, "tenant_id"):
            continue
        statement = statement.options(
            with_loader_criteria(
                model_class,
                lambda cls: cls.tenant_id == tenant_id,
                include_aliases=True,
            )
        )
    execute_state.statement = statement


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
