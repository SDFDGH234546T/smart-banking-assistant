"""Async repository for `chat_session` lifecycle and `chat_message` persistence."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from chat_app.constants import SESSION_STATUS_ACTIVE, SESSION_STATUS_EXPIRED
from chat_app.db.models import ChatMessage, ChatSession, default_task_state, local_now


def is_session_expired(
    session: ChatSession,
    ttl_seconds: int,
    now: datetime | None = None,
) -> bool:
    """判定会话是否超过空闲 TTL（默认 3600 秒），用于隔离 1 小时前的历史上下文。"""
    current_time = now or local_now()
    return (current_time - session.last_active_at).total_seconds() > ttl_seconds


async def get_active_session_if_valid(
    db: AsyncSession,
    sender_id: str,
    ttl_seconds: int,
    now: datetime | None = None,
) -> ChatSession | None:
    """只读获取未超时的活跃会话，供 /api/chat/history 使用。

    发现超时时不在此处写库更新 status，保持 GET 接口纯粹只读无副作用；
    状态切换统一收口在下次对话进入 get_or_create_active_session 时完成。
    """
    stmt = (
        select(ChatSession)
        .where(
            ChatSession.sender_id == sender_id,
            ChatSession.status == SESSION_STATUS_ACTIVE,
        )
        .order_by(ChatSession.last_active_at.desc(), ChatSession.id.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    session = result.scalar_one_or_none()
    if session is None or is_session_expired(session, ttl_seconds=ttl_seconds, now=now):
        return None
    return session


async def get_or_create_active_session(
    db: AsyncSession,
    sender_id: str,
    ttl_seconds: int,
    now: datetime | None = None,
) -> tuple[ChatSession, bool]:
    """获取有效活跃会话；若不存在或已超时，则置旧会话为 expired 并新建 active 会话。"""
    current_time = now or local_now()
    stmt = (
        select(ChatSession)
        .where(
            ChatSession.sender_id == sender_id,
            ChatSession.status == SESSION_STATUS_ACTIVE,
        )
        .order_by(ChatSession.last_active_at.desc(), ChatSession.id.desc())
    )
    result = await db.execute(stmt)
    active_sessions = list(result.scalars().all())

    if active_sessions and not is_session_expired(
        active_sessions[0], ttl_seconds=ttl_seconds, now=current_time
    ):
        latest = active_sessions[0]
        # 并发兜底：若因竞态存在多余的旧 active 会话，统一置为 expired 保证单客户仅 1 条活跃会话
        if len(active_sessions) > 1:
            stale_ids = [item.id for item in active_sessions[1:]]
            await db.execute(
                update(ChatSession)
                .where(ChatSession.id.in_(stale_ids))
                .values(status=SESSION_STATUS_EXPIRED, updated_at=current_time)
            )
            await db.commit()
        return latest, False

    if active_sessions:
        await db.execute(
            update(ChatSession)
            .where(
                ChatSession.sender_id == sender_id,
                ChatSession.status == SESSION_STATUS_ACTIVE,
            )
            .values(status=SESSION_STATUS_EXPIRED, updated_at=current_time)
        )

    new_session = ChatSession(
        session_id=f"SES{uuid4().hex}",
        sender_id=sender_id,
        status=SESSION_STATUS_ACTIVE,
        turn_count=0,
        last_active_at=current_time,
        cached_object_json=None,
        task_state_json=default_task_state(),
        created_at=current_time,
        updated_at=current_time,
    )
    db.add(new_session)
    await db.commit()
    await db.refresh(new_session)
    return new_session, True


async def get_recent_messages(
    db: AsyncSession,
    session_id: str,
    limit: int | None = 20,
) -> list[ChatMessage]:
    """按时间正序拉取会话消息；传入 limit 时先倒序截取最新 N 条再反转，兼顾性能与上下文顺序。"""
    if limit is None:
        stmt = (
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.id.asc())
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    stmt = (
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.id.desc())
        .limit(limit)
    )
    result = await db.execute(stmt)
    return list(reversed(list(result.scalars().all())))


async def save_turn(
    db: AsyncSession,
    session: ChatSession,
    *,
    user_content_type: Literal["text", "object"],
    user_text: str | None = None,
    user_object_payload: dict[str, Any] | None = None,
    bot_text: str,
    intent_category: str | None = None,
    intent_detail: str | None = None,
    task_state_json: dict[str, Any] | None = None,
    cached_object_json: dict[str, Any] | None = None,
    update_cached_object: bool = False,
    now: datetime | None = None,
) -> tuple[ChatMessage, ChatMessage]:
    """在同一事务内原子写入本轮用户/机器人消息，并更新会话轮次、活跃时间与任务状态。"""
    current_time = now or local_now()
    next_turn_no = session.turn_count + 1

    user_message = ChatMessage(
        session_id=session.session_id,
        sender_id=session.sender_id,
        turn_no=next_turn_no,
        role="user",
        content_type=user_content_type,
        text_content=user_text,
        object_payload_json=user_object_payload,
        intent_category=intent_category,
        intent_detail=intent_detail,
        created_at=current_time,
    )
    bot_message = ChatMessage(
        session_id=session.session_id,
        sender_id=session.sender_id,
        turn_no=next_turn_no,
        role="bot",
        content_type="text",
        text_content=bot_text,
        object_payload_json=None,
        intent_category=intent_category,
        intent_detail=intent_detail,
        created_at=current_time,
    )

    session.turn_count = next_turn_no
    session.last_active_at = current_time
    session.updated_at = current_time
    if task_state_json is not None:
        session.task_state_json = task_state_json
    # 仅在显式需要更新或清空缓存对象时才覆写，避免常规文本轮次误清已有焦点卡片
    if update_cached_object:
        session.cached_object_json = cached_object_json

    db.add_all([user_message, bot_message])
    await db.commit()
    await db.refresh(session)
    return user_message, bot_message
