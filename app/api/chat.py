from __future__ import annotations

import json
import re
import time
from collections.abc import Generator
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_tenant, get_current_user, get_tenant_scoped_db
from app.core.config import settings
from app.core.logging import get_logger
from app.db.models import Conversation, ConversationSummary, Message, MessageRole, Tenant, User
from app.prompting.prompt_builder import build_prompt_package
from app.providers.llm.base import ChatMessage
from app.providers.llm.gemini import GeminiProvider
from app.retrieval.pipeline import RetrievalPipeline
from app.retrieval.types import RetrievalItem, RetrievalResult

logger = get_logger(__name__)
router = APIRouter(prefix="/v1", tags=["chat"])


class ChatFilters(BaseModel):
    doc_ids: list[UUID] | None = None


class ChatRequest(BaseModel):
    conversation_id: UUID | None = None
    message: str = Field(min_length=1, max_length=16000)
    filters: ChatFilters | None = None


class CitationItem(BaseModel):
    id: str
    title: str
    doc_id: str
    page: int | None
    section: str | None


class SourceItem(BaseModel):
    citation_id: str
    chunk_id: str
    doc_id: str
    title: str
    page: int | None
    section: str | None
    score: float


class ChatResponse(BaseModel):
    answer: str
    citations: list[CitationItem]
    sources: list[SourceItem]
    timings: dict[str, float]
    retrieval_debug: dict[str, Any]


class ChatStreamRequest(BaseModel):
    conversation_id: UUID | None = None
    message: str = Field(min_length=1, max_length=16000)
    filters: ChatFilters | None = None


@router.post("/chat", response_model=ChatResponse)
def post_chat(
    payload: ChatRequest,
    db: Session = Depends(get_tenant_scoped_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
) -> ChatResponse:
    started_at = time.perf_counter()
    provider = GeminiProvider()

    conversation = _resolve_conversation(
        db=db,
        tenant_id=current_tenant.id,
        user_id=current_user.id,
        conversation_id=payload.conversation_id,
    )

    user_message = Message(
        tenant_id=current_tenant.id,
        conversation_id=conversation.id,
        role=MessageRole.USER,
        content=payload.message.strip(),
        citations_json=[],
        prompt_injection_detected=False,
    )
    db.add(user_message)
    conversation.last_message_at = datetime.now(timezone.utc)
    db.flush()

    memory_started_at = time.perf_counter()
    memory_prompt = _build_memory_prompt(
        db=db,
        conversation_id=conversation.id,
        latest_user_message_id=user_message.id,
    )
    memory_ms = (time.perf_counter() - memory_started_at) * 1000

    retrieval_started_at = time.perf_counter()
    retrieval_result = RetrievalPipeline(db=db, embedder=provider).retrieve(
        tenant_id=current_tenant.id,
        query=payload.message,
        doc_ids=(payload.filters.doc_ids if payload.filters else None),
    )
    retrieval_ms = (time.perf_counter() - retrieval_started_at) * 1000

    prompt_package = build_prompt_package(retrieval_result)
    model_messages: list[ChatMessage] = [
        {"role": "system", "content": prompt_package.system_prompt},
        {
            "role": "user",
            "content": "\n\n".join(
                [
                    memory_prompt,
                    prompt_package.context_prompt,
                    f"USER_QUESTION\n{payload.message.strip()}",
                    f"OUTPUT_FORMAT\n{prompt_package.output_format_spec}",
                ]
            ),
        },
    ]

    generation_started_at = time.perf_counter()
    raw_output = provider.generate(model_messages, streaming=False)
    if not isinstance(raw_output, str):
        raise RuntimeError("Non-streaming generation returned unexpected type")
    generation_ms = (time.perf_counter() - generation_started_at) * 1000

    parsed_answer, used_citation_ids = _parse_answer_and_citations(raw_output)
    citations, sources = _build_citation_payload(retrieval_result, used_citation_ids)

    assistant_message = Message(
        tenant_id=current_tenant.id,
        conversation_id=conversation.id,
        role=MessageRole.ASSISTANT,
        content=parsed_answer,
        citations_json=[citation.model_dump() for citation in citations],
        prompt_injection_detected=False,
    )
    db.add(assistant_message)
    conversation.last_message_at = datetime.now(timezone.utc)
    db.flush()

    summary_started_at = time.perf_counter()
    _maybe_refresh_summary(
        db=db,
        tenant_id=current_tenant.id,
        conversation_id=conversation.id,
        provider=provider,
    )
    summary_ms = (time.perf_counter() - summary_started_at) * 1000

    db.commit()

    timings = {
        "memory_ms": round(memory_ms, 2),
        "retrieval_ms": round(retrieval_ms, 2),
        "generation_ms": round(generation_ms, 2),
        "summary_ms": round(summary_ms, 2),
        "total_ms": round((time.perf_counter() - started_at) * 1000, 2),
    }

    return ChatResponse(
        answer=parsed_answer,
        citations=citations,
        sources=sources,
        timings=timings,
        retrieval_debug=retrieval_result.retrieval_debug,
    )


@router.post("/chat/stream")
def post_chat_stream(
    payload: ChatStreamRequest,
    db: Session = Depends(get_tenant_scoped_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
) -> StreamingResponse:
    started_at = time.perf_counter()
    provider = GeminiProvider()

    conversation = _resolve_conversation(
        db=db,
        tenant_id=current_tenant.id,
        user_id=current_user.id,
        conversation_id=payload.conversation_id,
    )

    user_message = Message(
        tenant_id=current_tenant.id,
        conversation_id=conversation.id,
        role=MessageRole.USER,
        content=payload.message.strip(),
        citations_json=[],
        prompt_injection_detected=False,
    )
    db.add(user_message)
    conversation.last_message_at = datetime.now(timezone.utc)
    db.flush()

    memory_started_at = time.perf_counter()
    memory_prompt = _build_memory_prompt(
        db=db,
        conversation_id=conversation.id,
        latest_user_message_id=user_message.id,
    )
    memory_ms = (time.perf_counter() - memory_started_at) * 1000

    retrieval_started_at = time.perf_counter()
    retrieval_result = RetrievalPipeline(db=db, embedder=provider).retrieve(
        tenant_id=current_tenant.id,
        query=payload.message,
        doc_ids=(payload.filters.doc_ids if payload.filters else None),
    )
    retrieval_ms = (time.perf_counter() - retrieval_started_at) * 1000

    prompt_package = build_prompt_package(retrieval_result)
    model_messages: list[ChatMessage] = [
        {"role": "system", "content": prompt_package.system_prompt},
        {
            "role": "user",
            "content": "\n\n".join(
                [
                    memory_prompt,
                    prompt_package.context_prompt,
                    f"USER_QUESTION\n{payload.message.strip()}",
                    f"OUTPUT_FORMAT\n{prompt_package.output_format_spec}",
                ]
            ),
        },
    ]

    def event_stream() -> Generator[str, None, None]:
        generation_started_at = time.perf_counter()
        usage: dict[str, int | None] = {
            "prompt_tokens": None,
            "completion_tokens": None,
            "total_tokens": None,
        }
        summary_ms = 0.0
        final_text_parts: list[str] = []

        try:
            stream = provider.generate(model_messages, streaming=True)
            if isinstance(stream, str):
                raise RuntimeError("Streaming generation returned unexpected type")

            for chunk in stream:
                if chunk.event == "token" and chunk.delta:
                    final_text_parts.append(chunk.delta)
                    yield _sse_event("token", {"delta": chunk.delta})
                elif chunk.event == "done":
                    chunk_usage = (chunk.metadata or {}).get("usage") if chunk.metadata else None
                    if isinstance(chunk_usage, dict):
                        usage = {
                            "prompt_tokens": _to_optional_int(chunk_usage.get("prompt_tokens")),
                            "completion_tokens": _to_optional_int(chunk_usage.get("completion_tokens")),
                            "total_tokens": _to_optional_int(chunk_usage.get("total_tokens")),
                        }

            generation_ms = (time.perf_counter() - generation_started_at) * 1000
            raw_output = "".join(final_text_parts)
            parsed_answer, used_citation_ids = _parse_answer_and_citations(raw_output)
            citations, sources = _build_citation_payload(retrieval_result, used_citation_ids)

            assistant_message = Message(
                tenant_id=current_tenant.id,
                conversation_id=conversation.id,
                role=MessageRole.ASSISTANT,
                content=parsed_answer,
                citations_json=[citation.model_dump() for citation in citations],
                prompt_injection_detected=False,
            )
            db.add(assistant_message)
            conversation.last_message_at = datetime.now(timezone.utc)
            db.flush()

            summary_started_at = time.perf_counter()
            _maybe_refresh_summary(
                db=db,
                tenant_id=current_tenant.id,
                conversation_id=conversation.id,
                provider=provider,
            )
            summary_ms = (time.perf_counter() - summary_started_at) * 1000
            db.commit()

            timings = {
                "memory_ms": round(memory_ms, 2),
                "retrieval_ms": round(retrieval_ms, 2),
                "generation_ms": round(generation_ms, 2),
                "summary_ms": round(summary_ms, 2),
                "total_ms": round((time.perf_counter() - started_at) * 1000, 2),
            }

            yield _sse_event(
                "final",
                {
                    "answer": parsed_answer,
                    "citations": [citation.model_dump() for citation in citations],
                    "sources": [source.model_dump() for source in sources],
                    "usage": usage,
                    "timings": timings,
                    "retrieval_debug": retrieval_result.retrieval_debug,
                },
            )
        except Exception as exc:
            db.rollback()
            yield _sse_event("error", {"message": str(exc)})

    headers = {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    }
    return StreamingResponse(event_stream(), media_type="text/event-stream", headers=headers)


def _resolve_conversation(
    *,
    db: Session,
    tenant_id: UUID,
    user_id: UUID,
    conversation_id: UUID | None,
) -> Conversation:
    if conversation_id is None:
        conversation = Conversation(tenant_id=tenant_id, user_id=user_id)
        db.add(conversation)
        db.flush()
        return conversation

    conversation = db.scalar(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.tenant_id == tenant_id,
        )
    )
    if conversation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="conversation_not_found")
    if conversation.user_id is not None and conversation.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="conversation_access_denied")
    return conversation


def _build_memory_prompt(db: Session, conversation_id: UUID, latest_user_message_id: UUID) -> str:
    latest_summary = db.scalar(
        select(ConversationSummary)
        .where(ConversationSummary.conversation_id == conversation_id)
        .order_by(ConversationSummary.summary_index.desc())
        .limit(1)
    )

    recent_messages = list(
        db.scalars(
            select(Message)
            .where(
                Message.conversation_id == conversation_id,
                Message.id != latest_user_message_id,
                Message.role.in_([MessageRole.USER, MessageRole.ASSISTANT]),
            )
            .order_by(Message.created_at.desc())
            .limit(max(settings.chat_memory_turns * 2, 1))
        ).all()
    )
    recent_messages = recent_messages[::-1]

    lines = ["CONVERSATION_MEMORY", ""]
    if latest_summary is not None:
        lines.extend(["SUMMARY", latest_summary.summary_text.strip(), ""])
    else:
        lines.extend(["SUMMARY", "No prior summary.", ""])

    lines.append("RECENT_TURNS")
    if not recent_messages:
        lines.append("No recent turns.")
    else:
        for msg in recent_messages:
            role = "USER" if msg.role == MessageRole.USER else "ASSISTANT"
            lines.append(f"{role}: {msg.content.strip()}")

    return "\n".join(lines).strip()


def _parse_answer_and_citations(raw_output: str) -> tuple[str, list[str]]:
    answer_match = re.search(r"(?is)^\s*Answer\s*$\n(.*?)(?:\n\s*Citations\s*$\n|\Z)", raw_output, re.MULTILINE)
    if answer_match:
        answer = answer_match.group(1).strip()
    else:
        answer = raw_output.strip()

    citation_ids: list[str] = []
    for citation_id in re.findall(r"\[(\d+)\]", answer):
        if citation_id not in citation_ids:
            citation_ids.append(citation_id)
    return answer, citation_ids


def _build_citation_payload(
    retrieval_result: RetrievalResult,
    used_citation_ids: list[str],
) -> tuple[list[CitationItem], list[SourceItem]]:
    by_citation_id: dict[str, RetrievalItem] = {
        item.citation_id: item for item in retrieval_result.items
    }

    selected_ids = [citation_id for citation_id in used_citation_ids if citation_id in by_citation_id]
    if not selected_ids and retrieval_result.items:
        selected_ids = [retrieval_result.items[0].citation_id]

    citations: list[CitationItem] = []
    sources: list[SourceItem] = []
    for citation_id in selected_ids:
        item = by_citation_id[citation_id]
        title = str(item.metadata.get("title") or "Untitled")
        citations.append(
            CitationItem(
                id=citation_id,
                title=title,
                doc_id=item.doc_id,
                page=item.page,
                section=item.section,
            )
        )
        sources.append(
            SourceItem(
                citation_id=citation_id,
                chunk_id=item.chunk_id,
                doc_id=item.doc_id,
                title=title,
                page=item.page,
                section=item.section,
                score=item.score,
            )
        )

    return citations, sources


def _maybe_refresh_summary(
    *,
    db: Session,
    tenant_id: UUID,
    conversation_id: UUID,
    provider: GeminiProvider,
) -> None:
    refresh_every = max(settings.chat_summary_refresh_turns, 1)
    user_turns = db.scalar(
        select(func.count(Message.id)).where(
            Message.conversation_id == conversation_id,
            Message.role == MessageRole.USER,
        )
    )
    if not isinstance(user_turns, int) or user_turns == 0 or user_turns % refresh_every != 0:
        return

    latest_summary = db.scalar(
        select(ConversationSummary)
        .where(ConversationSummary.conversation_id == conversation_id)
        .order_by(ConversationSummary.summary_index.desc())
        .limit(1)
    )

    new_messages_query = select(Message).where(
        Message.conversation_id == conversation_id,
        Message.role.in_([MessageRole.USER, MessageRole.ASSISTANT]),
    )
    if latest_summary is not None and latest_summary.up_to_message_id is not None:
        cutoff = db.scalar(
            select(Message.created_at).where(
                Message.id == latest_summary.up_to_message_id,
                Message.conversation_id == conversation_id,
            )
        )
        if cutoff is not None:
            new_messages_query = new_messages_query.where(Message.created_at > cutoff)

    new_messages = db.scalars(new_messages_query.order_by(Message.created_at.asc())).all()
    if not new_messages:
        return

    transcript_lines: list[str] = []
    for msg in new_messages:
        role = "USER" if msg.role == MessageRole.USER else "ASSISTANT"
        transcript_lines.append(f"{role}: {msg.content.strip()}")

    previous_summary = latest_summary.summary_text.strip() if latest_summary is not None else "No prior summary."
    summary_prompt = (
        "Summarize the conversation state for future retrieval. Keep factual details, user goals, "
        "constraints, decisions, and unresolved questions. Do not include secrets.\n\n"
        f"PREVIOUS_SUMMARY\n{previous_summary}\n\n"
        f"NEW_MESSAGES\n{'\n'.join(transcript_lines)}"
    )

    try:
        summary_raw = provider.generate(
            [
                {
                    "role": "system",
                    "content": "You summarize chat history for memory. Be concise and factual.",
                },
                {"role": "user", "content": summary_prompt},
            ],
            streaming=False,
        )
    except Exception:
        logger.exception(
            "conversation_summary_refresh_failed",
            tenant_id=str(tenant_id),
            conversation_id=str(conversation_id),
        )
        return

    if not isinstance(summary_raw, str) or not summary_raw.strip():
        return

    summary_index = 1 if latest_summary is None else latest_summary.summary_index + 1
    db.add(
        ConversationSummary(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            summary_index=summary_index,
            summary_text=summary_raw.strip(),
            up_to_message_id=new_messages[-1].id,
        )
    )


def _sse_event(event: str, payload: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, separators=(',', ':'))}\n\n"


def _to_optional_int(value: Any) -> int | None:
    return value if isinstance(value, int) else None
