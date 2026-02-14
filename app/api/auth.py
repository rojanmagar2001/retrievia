from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_tenant, get_current_user
from app.core.config import settings
from app.db.models import Tenant, TenantStatus, User
from app.db.session import get_db
from app.security.jwt import create_access_token
from app.security.password import get_password_hash, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=12, max_length=256)
    full_name: str | None = Field(default=None, max_length=255)


class RegisterResponse(BaseModel):
    user_id: str
    tenant_id: str
    email: str


@router.post("/register", status_code=status.HTTP_201_CREATED, response_model=RegisterResponse)
def register_user(
    payload: RegisterRequest,
    db: Session = Depends(get_db),
    x_tenant_id: str = Header(alias="X-Tenant-Id"),
) -> RegisterResponse:
    try:
        tenant_id = UUID(x_tenant_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid_tenant_id") from exc

    tenant = db.get(Tenant, tenant_id)
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="tenant_not_found")
    if tenant.status != TenantStatus.ACTIVE:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="tenant_inactive")

    existing = db.scalar(select(User).where(User.tenant_id == tenant_id, User.email == payload.email))
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="email_already_exists")

    user = User(
        tenant_id=tenant_id,
        email=payload.email,
        full_name=payload.full_name,
        password_hash=get_password_hash(payload.password),
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    return RegisterResponse(user_id=str(user.id), tenant_id=str(tenant_id), email=user.email)


@router.post("/login")
def login_for_access_token(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
    x_tenant_id: str = Header(alias="X-Tenant-Id"),
) -> dict[str, str | int]:
    try:
        tenant_id = UUID(x_tenant_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid_tenant_id") from exc

    user = db.scalar(select(User).where(User.tenant_id == tenant_id, User.email == form_data.username))
    if user is None or not verify_password(form_data.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid_credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="user_inactive")

    tenant = db.get(Tenant, tenant_id)
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="tenant_not_found")

    token = create_access_token(subject=str(user.id), tenant_id=str(tenant.id))
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": 60 * settings.jwt_access_token_expire_minutes,
    }


@router.get("/me")
def read_current_principal(
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
) -> dict[str, str]:
    return {
        "user_id": str(current_user.id),
        "tenant_id": str(current_tenant.id),
        "email": current_user.email,
    }
