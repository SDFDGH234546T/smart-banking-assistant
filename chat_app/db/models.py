"""SQLAlchemy 2.0 ORM models for `chat_session` and `chat_message`."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import JSON, BigInteger, DateTime, Index, Integer, String, Text
from sqlalchemy.ext.asyncio import AsyncAttrs
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from chat_app.constants import SESSION_STATUS_ACTIVE

LOCAL_TZ = ZoneInfo("Asia/Shanghai")


def local_now() -> datetime:
    """生成 Asia/Shanghai 本地无时区时间，与中台 app/utils.py 保持同一口径以防超时计算偏差。"""
    return datetime.now(LOCAL_TZ).replace(tzinfo=None)


def default_task_state() -> dict[str, Any]:
    """每次实例化新字典作为 task_state_json 默认值，避免多条记录共享可变对象。"""
    return {"active_task": None, "suspended_tasks": []}


class Base(AsyncAttrs, DeclarativeBase):
    """Base declarative class supporting SQLAlchemy 2.0 async attributes."""


class ChatSession(Base):
    """客服会话生命周期、双区任务状态与焦点对象缓存表。"""

    __tablename__ = "chat_session"
    # 联合索引用于按 sender_id + status 快速定位最新活跃会话并判定 1 小时超时
    __table_args__ = (
        Index("idx_chat_session_sender_status", "sender_id", "status", "last_active_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    sender_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=SESSION_STATUS_ACTIVE
    )
    turn_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_active_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=local_now
    )
    cached_object_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True, default=None
    )
    task_state_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=default_task_state
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=local_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=local_now, onupdate=local_now
    )


class ChatMessage(Base):
    """客服对话消息持久化表（与中台业务表物理隔离）。"""

    __tablename__ = "chat_message"
    # 按客户号或会话号按自增主键顺序拉取滑动窗口历史消息
    __table_args__ = (
        Index("idx_chat_message_sender_id_id", "sender_id", "id"),
        Index("idx_chat_message_session_id_id", "session_id", "id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    sender_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    turn_no: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content_type: Mapped[str] = mapped_column(String(16), nullable=False)
    text_content: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    object_payload_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True, default=None
    )
    intent_category: Mapped[str | None] = mapped_column(
        String(32), nullable=True, default=None
    )
    intent_detail: Mapped[str | None] = mapped_column(
        String(64), nullable=True, default=None
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=local_now
    )
