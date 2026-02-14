from collections.abc import Generator
from uuid import UUID

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.db.models import Tenant, TenantStatus, User
from app.db.session import get_db, reset_current_tenant_id, set_current_tenant_id
from app.security.jwt import TokenError, decode_access_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


def _unauthorized(detail: str = "invalid_credentials") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_current_user(
    db: Session = Depends(get_db),
    token: str = Depends(oauth2_scheme),
) -> User:
    try:
        payload = decode_access_token(token)
    except TokenError as exc:
        raise _unauthorized(str(exc)) from exc

    try:
        user_id = UUID(payload["sub"])
        tenant_id = UUID(payload["tenant_id"])
    except ValueError as exc:
        raise _unauthorized("invalid_subject") from exc

    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise _unauthorized("user_not_found_or_inactive")
    if user.tenant_id != tenant_id:
        raise _unauthorized("tenant_mismatch")
    return user


def get_current_tenant(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-Id"),
) -> Tenant:
    tenant = db.get(Tenant, current_user.tenant_id)
    if tenant is None or tenant.status != TenantStatus.ACTIVE:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="tenant_inactive_or_missing")
    if x_tenant_id is not None and x_tenant_id != str(tenant.id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="tenant_header_mismatch")
    return tenant


def get_tenant_scoped_db(
    db: Session = Depends(get_db),
    current_tenant: Tenant = Depends(get_current_tenant),
) -> Generator[Session, None, None]:
    token = set_current_tenant_id(current_tenant.id)
    try:
        yield db
    finally:
        reset_current_tenant_id(token)
