"""Per-tender chat over Server-Sent Events. Signed-in users' chats are stored under their
org; anonymous (public demo) chats are scoped to their session id via RLS."""

import json
import uuid
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.deps import MaybeUser, client_ip, rate_limit
from apps.api.schemas import ChatMessageOut, ChatRequest
from core.agent.chat import answer, save_turn
from core.config import get_settings
from core.db.session import get_sessionmaker, set_org_context
from core.llm.claude import CallContext, Claude, LLMRefusal

router = APIRouter(tags=["chat"])


async def _scope(session: AsyncSession, org_id: uuid.UUID | None, chat_session: uuid.UUID) -> None:
    if org_id is not None:
        await set_org_context(session, org_id)
    await session.execute(
        text("SELECT set_config('app.chat_session_id', :s, true)"), {"s": str(chat_session)}
    )


def _sse(event: dict[str, Any]) -> str:
    return f"event: {event['type']}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"


@router.post("/tenders/{tender_id}/chat")
async def chat(
    tender_id: int, body: ChatRequest, user: MaybeUser, request: Request
) -> StreamingResponse:
    if not get_settings().llm_configured:
        raise HTTPException(503, "chat needs ANTHROPIC_API_KEY to be configured")
    if user:
        await rate_limit(f"chat:user:{user.id}", limit=60, window_s=3600)
    else:
        await rate_limit(f"chat:ip:{client_ip(request)}", limit=15, window_s=3600)
    org_id = user.org_id if user else None

    async def events() -> AsyncIterator[str]:
        # The session lives inside the generator: it must stay open while streaming.
        async with get_sessionmaker()() as session:
            async with session.begin():
                await _scope(session, org_id, body.session_id)
                rows = (
                    await session.execute(
                        text(
                            "SELECT role, content FROM chat_messages WHERE session_id = :s "
                            "AND tender_id = :t ORDER BY id"
                        ),
                        {"s": body.session_id, "t": tender_id},
                    )
                ).all()
                history = [{"role": r.role, "content": r.content} for r in rows]
                ctx = CallContext(purpose="chat", org_id=org_id, trace_id=f"chat:{body.session_id}")
                done: dict[str, Any] | None = None
                try:
                    async for event in answer(
                        session, Claude(), tender_id, body.question, history, ctx
                    ):
                        if event["type"] == "done":
                            done = event
                        yield _sse(event)
                except LLMRefusal:
                    yield _sse({"type": "error", "message": "The model declined to answer."})
                if done is not None:
                    await save_turn(
                        session,
                        body.session_id,
                        org_id,
                        tender_id,
                        body.question,
                        done["text"],
                        done["cited"],
                    )

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/tenders/{tender_id}/chat/{session_id}")
async def chat_history(
    tender_id: int, session_id: uuid.UUID, user: MaybeUser
) -> list[ChatMessageOut]:
    async with get_sessionmaker()() as session, session.begin():
        await _scope(session, user.org_id if user else None, session_id)
        rows = (
            (
                await session.execute(
                    text(
                        "SELECT role, content, cited_clause_ids, created_at FROM chat_messages "
                        "WHERE session_id = :s AND tender_id = :t ORDER BY id"
                    ),
                    {"s": session_id, "t": tender_id},
                )
            )
            .mappings()
            .all()
        )
    return [ChatMessageOut(**r) for r in rows]
