"""External HTTP API routes aligned with `web/src/App.vue`."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from chat_app.config import get_settings
from chat_app.constants import HISTORY_DIVIDER_TEXT
from chat_app.db.engine import get_db_session
from chat_app.db.repository import get_active_session_if_valid, get_recent_messages
from chat_app.orchestrator.engine import ChatOrchestrator
from chat_app.schemas.chat import (
    ChatRequest,
    ChatResponse,
    HistoryMessage,
    HistoryResponse,
    ObjectPayload,
)

router = APIRouter(prefix="/api", tags=["chat"])


def get_orchestrator(request: Request) -> ChatOrchestrator:
    """从 FastAPI app.state 获取已装配的对话主编排器。"""
    orchestrator = getattr(request.app.state, "orchestrator", None)
    if orchestrator is None:
        raise HTTPException(
            status_code=503,
            detail="智能客服服务尚未初始化完成，请稍后重试。",
        )
    return orchestrator


@router.post("/chat", response_model=ChatResponse, summary="发送对话消息（非流式同步）")
async def post_chat(
    payload: ChatRequest,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    orchestrator: Annotated[ChatOrchestrator, Depends(get_orchestrator)],
) -> ChatResponse:
    """接收纯文本或对象卡片输入，返回非流式同步机器人回复。"""
    return await orchestrator.handle_chat(db, payload)


@router.get("/chat/history", response_model=HistoryResponse, summary="获取当前活跃会话历史消息")
async def get_chat_history(
    sender_id: Annotated[str, Query(min_length=1, description="客户编号，如 CUS00000001")],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> HistoryResponse:
    """仅返回 1 小时内活跃会话的消息；超时或无会话时返回空列表。"""
    cleaned_sender_id = sender_id.strip()
    if not cleaned_sender_id:
        raise HTTPException(status_code=422, detail="sender_id 不能为空")

    settings = get_settings()
    session = await get_active_session_if_valid(
        db,
        cleaned_sender_id,
        ttl_seconds=settings.CHAT_SESSION_TTL_SECONDS,
    )
    if session is None:
        return HistoryResponse(messages=[])

    rows = await get_recent_messages(db, session.session_id, limit=None)
    messages: list[HistoryMessage] = []
    for row in rows:
        role = "bot" if row.role == "bot" else "user"
        obj_payload = (
            ObjectPayload.model_validate(row.object_payload_json)
            if row.object_payload_json
            else None
        )
        # 防御性跳过既无文本又无对象的异常历史行，避免 Pydantic 校验触发 500
        if row.text_content is None and obj_payload is None:
            continue
        messages.append(
            HistoryMessage(
                role=role,
                text=row.text_content,
                object=obj_payload,
            )
        )

    if messages:
        messages.append(HistoryMessage(role="divider", text=HISTORY_DIVIDER_TEXT))

    return HistoryResponse(messages=messages)
