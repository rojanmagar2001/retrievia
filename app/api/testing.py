from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.chat import ChatFilters, ChatRequest, ChatResponse, post_chat
from app.auth.dependencies import get_current_tenant, get_current_user, get_tenant_scoped_db
from app.core.config import settings
from app.db.models import Conversation, Document, Tenant, User
from app.testing.seed_fixtures import SEEDED_CONVERSATIONS, SEEDED_DOCS

router = APIRouter(prefix="/v1/testing", tags=["testing"])


class SeedConversationDescriptor(BaseModel):
    key: str
    title: str
    conversation_id: str | None
    default_question: str
    doc_ids: list[str]


class SeedConversationsResponse(BaseModel):
    items: list[SeedConversationDescriptor]


def _assert_testing_enabled() -> None:
    if settings.app_env not in {"development", "test"}:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")


@router.get("/conversations", response_model=SeedConversationsResponse)
def list_seeded_conversations(
    db: Session = Depends(get_tenant_scoped_db),
    current_tenant: Tenant = Depends(get_current_tenant),
) -> SeedConversationsResponse:
    _assert_testing_enabled()

    items: list[SeedConversationDescriptor] = []
    for fixture in SEEDED_CONVERSATIONS:
        conversation = db.scalar(
            select(Conversation).where(
                Conversation.tenant_id == current_tenant.id,
                Conversation.title == fixture.title,
            )
        )
        docs = db.scalars(
            select(Document).where(
                Document.tenant_id == current_tenant.id,
                Document.external_id.in_([
                    _doc_external_id_from_key(key) for key in fixture.doc_keys
                ]),
            )
        ).all()

        items.append(
            SeedConversationDescriptor(
                key=fixture.key,
                title=fixture.title,
                conversation_id=(str(conversation.id) if conversation is not None else None),
                default_question=fixture.default_question,
                doc_ids=[str(doc.id) for doc in docs],
            )
        )

    return SeedConversationsResponse(items=items)


@router.post("/conversations/{conversation_key}/chat", response_model=ChatResponse)
def chat_seeded_conversation(
    conversation_key: str,
    db: Session = Depends(get_tenant_scoped_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
) -> ChatResponse:
    _assert_testing_enabled()

    fixture = next((item for item in SEEDED_CONVERSATIONS if item.key == conversation_key), None)
    if fixture is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="seed_conversation_not_found")

    conversation = db.scalar(
        select(Conversation).where(
            Conversation.tenant_id == current_tenant.id,
            Conversation.title == fixture.title,
        )
    )
    if conversation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="seeded_conversation_missing")

    docs = db.scalars(
        select(Document).where(
            Document.tenant_id == current_tenant.id,
            Document.external_id.in_([_doc_external_id_from_key(key) for key in fixture.doc_keys]),
        )
    ).all()
    doc_ids = [doc.id for doc in docs]

    payload = ChatRequest(
        conversation_id=conversation.id,
        message=fixture.default_question,
        filters=(ChatFilters(doc_ids=doc_ids) if doc_ids else None),
    )
    return post_chat(payload=payload, db=db, current_user=current_user, current_tenant=current_tenant)


@router.post("/conversations/{conversation_id}/chat", response_model=ChatResponse)
def chat_existing_conversation(
    conversation_id: UUID,
    payload: ChatRequest,
    db: Session = Depends(get_tenant_scoped_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
) -> ChatResponse:
    _assert_testing_enabled()
    payload_with_conversation = ChatRequest(
        conversation_id=conversation_id,
        message=payload.message,
        filters=payload.filters,
    )
    return post_chat(
        payload=payload_with_conversation,
        db=db,
        current_user=current_user,
        current_tenant=current_tenant,
    )


def _doc_external_id_from_key(key: str) -> str:
    mapping = {fixture.key: fixture.external_id for fixture in SEEDED_DOCS}
    return mapping[key]
