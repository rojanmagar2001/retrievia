from __future__ import annotations

import tempfile
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select

from app.db.models import (
    Conversation,
    ConversationSummary,
    Document,
    Message,
    MessageRole,
    Tenant,
    TenantStatus,
    User,
)
from app.db.session import SessionLocal, reset_current_tenant_id, set_current_tenant_id
from app.ingestion.pipeline import ingest_document_pipeline
from app.testing.seed_fixtures import SEEDED_CONVERSATIONS, SEEDED_DOCS


def _first_active_user_for_tenant(db, tenant_id) -> User | None:
    return db.scalar(
        select(User)
        .where(User.tenant_id == tenant_id, User.is_active.is_(True))
        .order_by(User.created_at.asc())
        .limit(1)
    )


def _ensure_document_for_tenant(db, *, tenant: Tenant, user: User | None, fixture, source_path: Path) -> Document:
    document = db.scalar(
        select(Document).where(Document.tenant_id == tenant.id, Document.external_id == fixture.external_id)
    )
    if document is None:
        document = Document(
            id=uuid4(),
            tenant_id=tenant.id,
            title=fixture.title,
            source_uri=str(source_path),
            external_id=fixture.external_id,
            created_by_user_id=(user.id if user is not None else None),
        )
        db.add(document)
        db.flush()
    else:
        document.title = fixture.title
        document.source_uri = str(source_path)

    return document


def _ensure_seed_conversation(db, *, tenant: Tenant, user: User | None, fixture) -> Conversation:
    conversation = db.scalar(
        select(Conversation).where(Conversation.tenant_id == tenant.id, Conversation.title == fixture.title)
    )
    if conversation is None:
        conversation = Conversation(
            id=uuid4(),
            tenant_id=tenant.id,
            user_id=(user.id if user is not None else None),
            title=fixture.title,
        )
        db.add(conversation)
        db.flush()

    has_messages = db.scalar(
        select(Message.id).where(Message.conversation_id == conversation.id).limit(1)
    )
    if has_messages is None:
        user_message = Message(
            id=uuid4(),
            tenant_id=tenant.id,
            conversation_id=conversation.id,
            role=MessageRole.USER,
            content=fixture.opening_user_message,
            citations_json=[],
            prompt_injection_detected=False,
        )
        assistant_message = Message(
            id=uuid4(),
            tenant_id=tenant.id,
            conversation_id=conversation.id,
            role=MessageRole.ASSISTANT,
            content=fixture.opening_assistant_message,
            citations_json=[],
            prompt_injection_detected=False,
        )
        db.add(user_message)
        db.add(assistant_message)
        db.flush()

        summary = ConversationSummary(
            id=uuid4(),
            tenant_id=tenant.id,
            conversation_id=conversation.id,
            summary_index=1,
            summary_text=(
                "Seeded conversation context: "
                f"{fixture.opening_user_message} / {fixture.opening_assistant_message}"
            ),
            up_to_message_id=assistant_message.id,
        )
        db.add(summary)

    return conversation


def main() -> None:
    with SessionLocal() as db:
        tenants = db.scalars(
            select(Tenant).where(Tenant.status == TenantStatus.ACTIVE).order_by(Tenant.slug.asc())
        ).all()

        if not tenants:
            print("No active tenants found. Run scripts/seed_test_auth_data.py first.")
            return

        with tempfile.TemporaryDirectory(prefix="retrievia-seed-") as tmp_dir:
            tmp_root = Path(tmp_dir)
            for tenant in tenants:
                print(f"Seeding tenant {tenant.slug} ({tenant.id})")
                user = _first_active_user_for_tenant(db, tenant.id)
                tenant_token = set_current_tenant_id(tenant.id)

                try:
                    doc_ids_by_key: dict[str, str] = {}
                    for fixture in SEEDED_DOCS:
                        source_path = tmp_root / f"{tenant.slug}_{fixture.source_filename}"
                        source_path.write_text(fixture.markdown, encoding="utf-8")

                        document = _ensure_document_for_tenant(
                            db,
                            tenant=tenant,
                            user=user,
                            fixture=fixture,
                            source_path=source_path,
                        )
                        db.commit()

                        result = ingest_document_pipeline(db=db, document_id=document.id, source=str(source_path))
                        doc_ids_by_key[fixture.key] = str(document.id)
                        print(
                            f"  document {fixture.external_id} -> doc_id={document.id} chunks={result['chunks']} status={result['status']}"
                        )

                    for fixture in SEEDED_CONVERSATIONS:
                        conversation = _ensure_seed_conversation(db, tenant=tenant, user=user, fixture=fixture)
                        db.commit()
                        filtered_doc_ids = [doc_ids_by_key[key] for key in fixture.doc_keys if key in doc_ids_by_key]
                        print(
                            f"  conversation {fixture.key} -> conversation_id={conversation.id} default_question={fixture.default_question} doc_ids={filtered_doc_ids}"
                        )
                finally:
                    reset_current_tenant_id(tenant_token)


if __name__ == "__main__":
    main()
