from __future__ import annotations

from uuid import uuid4

from sqlalchemy import select

from app.db.models import Tenant, TenantStatus, User
from app.db.session import SessionLocal
from app.security.password import get_password_hash


def ensure_tenant_and_user(*, slug: str, tenant_name: str, email: str, password: str, full_name: str) -> None:
    with SessionLocal() as db:
        tenant = db.scalar(select(Tenant).where(Tenant.slug == slug))
        if tenant is None:
            tenant = Tenant(
                id=uuid4(),
                slug=slug,
                name=tenant_name,
                status=TenantStatus.ACTIVE,
            )
            db.add(tenant)
            db.flush()

        user = db.scalar(select(User).where(User.tenant_id == tenant.id, User.email == email))
        if user is None:
            user = User(
                id=uuid4(),
                tenant_id=tenant.id,
                email=email,
                full_name=full_name,
                password_hash=get_password_hash(password),
                is_active=True,
            )
            db.add(user)
            db.flush()

        db.commit()

        print(f"tenant_slug={tenant.slug}")
        print(f"tenant_id={tenant.id}")
        print(f"email={user.email}")
        print(f"password={password}")
        print("---")


def main() -> None:
    ensure_tenant_and_user(
        slug="acme-test",
        tenant_name="Acme Test",
        email="admin@acme-test.local",
        password="ChangeMe12345!",
        full_name="Acme Admin",
    )

    ensure_tenant_and_user(
        slug="globex-test",
        tenant_name="Globex Test",
        email="admin@globex-test.local",
        password="ChangeMe12345!",
        full_name="Globex Admin",
    )


if __name__ == "__main__":
    main()
