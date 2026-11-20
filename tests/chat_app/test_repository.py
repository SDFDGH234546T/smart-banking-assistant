"""Offline unit tests for `chat_app.db.repository`."""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from chat_app.constants import SESSION_STATUS_ACTIVE
from chat_app.db.models import ChatMessage, ChatSession, default_task_state
from chat_app.db.repository import (
    get_active_session_if_valid,
    get_or_create_active_session,
    get_recent_messages,
    is_session_expired,
    save_turn,
)


def _make_session(
    *,
    session_id: str = "SES123",
    sender_id: str = "CUS00000001",
    last_active_at: datetime,
    turn_count: int = 2,
) -> ChatSession:
    return ChatSession(
        id=1,
        session_id=session_id,
        sender_id=sender_id,
        status=SESSION_STATUS_ACTIVE,
        turn_count=turn_count,
        last_active_at=last_active_at,
        cached_object_json={"type": "account", "id": "ACC0000000001"},
        task_state_json=default_task_state(),
        created_at=last_active_at,
        updated_at=last_active_at,
    )


def _mock_scalar_result(items: list[object]) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = items[0] if items else None
    scalars_mock = MagicMock()
    scalars_mock.all.return_value = items
    result.scalars.return_value = scalars_mock
    return result


def _make_async_db() -> MagicMock:
    db = MagicMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.add = MagicMock()
    db.add_all = MagicMock()
    return db


def test_is_session_expired_boundary() -> None:
    now = datetime(2026, 11, 20, 12, 0, 0)
    valid = _make_session(last_active_at=now - timedelta(seconds=3600))
    expired = _make_session(last_active_at=now - timedelta(seconds=3601))

    assert is_session_expired(valid, ttl_seconds=3600, now=now) is False
    assert is_session_expired(expired, ttl_seconds=3600, now=now) is True


@pytest.mark.anyio
async def test_get_active_session_if_valid_is_readonly() -> None:
    now = datetime(2026, 11, 20, 12, 0, 0)
    db = _make_async_db()

    # 未超时 -> 返回会话
    valid_session = _make_session(last_active_at=now - timedelta(minutes=10))
    db.execute.return_value = _mock_scalar_result([valid_session])
    got = await get_active_session_if_valid(db, "CUS00000001", ttl_seconds=3600, now=now)
    assert got is valid_session
    db.commit.assert_not_awaited()

    # 已超时 -> 返回 None 且不写库
    expired_session = _make_session(last_active_at=now - timedelta(hours=2))
    db.execute.return_value = _mock_scalar_result([expired_session])
    got_expired = await get_active_session_if_valid(
        db, "CUS00000001", ttl_seconds=3600, now=now
    )
    assert got_expired is None
    db.commit.assert_not_awaited()


@pytest.mark.anyio
async def test_get_or_create_active_session_creates_when_missing_or_expired() -> None:
    now = datetime(2026, 11, 20, 12, 0, 0)
    db = _make_async_db()

    # 1. 不存在活跃会话 -> 新建
    db.execute.return_value = _mock_scalar_result([])
    created, is_new = await get_or_create_active_session(
        db, "CUS00000001", ttl_seconds=3600, now=now
    )
    assert is_new is True
    assert created.session_id.startswith("SES")
    assert created.status == SESSION_STATUS_ACTIVE
    assert created.turn_count == 0
    db.add.assert_called_once_with(created)
    db.commit.assert_awaited_once()
    db.refresh.assert_awaited_once_with(created)

    # 2. 存在未超时会话 -> 直接复用
    db.reset_mock()
    valid = _make_session(last_active_at=now - timedelta(minutes=5))
    db.execute.return_value = _mock_scalar_result([valid])
    reused, is_new2 = await get_or_create_active_session(
        db, "CUS00000001", ttl_seconds=3600, now=now
    )
    assert is_new2 is False
    assert reused is valid
    db.commit.assert_not_awaited()

    # 3. 存在已超时会话 -> 批量置 expired 并新建
    db.reset_mock()
    expired = _make_session(last_active_at=now - timedelta(seconds=3601))
    db.execute.side_effect = [_mock_scalar_result([expired]), MagicMock()]
    renewed, is_new3 = await get_or_create_active_session(
        db, "CUS00000001", ttl_seconds=3600, now=now
    )
    assert is_new3 is True
    assert renewed.turn_count == 0
    assert db.execute.await_count == 2
    db.commit.assert_awaited_once()


@pytest.mark.anyio
async def test_get_recent_messages_returns_chronological_order() -> None:
    db = _make_async_db()
    msg_new = ChatMessage(
        id=10,
        session_id="SES1",
        sender_id="CUS1",
        turn_no=2,
        role="bot",
        content_type="text",
        text_content="B",
    )
    msg_old = ChatMessage(
        id=9,
        session_id="SES1",
        sender_id="CUS1",
        turn_no=2,
        role="user",
        content_type="text",
        text_content="A",
    )
    # 模拟 SQL 按 id DESC 返回 [msg_new, msg_old]
    db.execute.return_value = _mock_scalar_result([msg_new, msg_old])

    messages = await get_recent_messages(db, "SES1", limit=20)
    assert [m.id for m in messages] == [9, 10]


@pytest.mark.anyio
async def test_save_turn_updates_session_and_persists_messages() -> None:
    now = datetime(2026, 11, 20, 12, 30, 0)
    db = _make_async_db()
    session = _make_session(last_active_at=now - timedelta(minutes=3), turn_count=2)
    new_task_state = {"active_task": {"task_type": "query_balance"}, "suspended_tasks": []}

    user_msg, bot_msg = await save_turn(
        db,
        session,
        user_content_type="text",
        user_text="查一下余额",
        bot_text="您的可用余额为 12500.00 元。",
        intent_category="task_flow",
        intent_detail="query_balance",
        task_state_json=new_task_state,
        update_cached_object=False,
        now=now,
    )

    assert user_msg.turn_no == 3
    assert bot_msg.turn_no == 3
    assert user_msg.role == "user"
    assert bot_msg.role == "bot"
    assert session.turn_count == 3
    assert session.last_active_at == now
    assert session.task_state_json == new_task_state
    # 未开启 update_cached_object 时保留原有缓存对象
    assert session.cached_object_json == {"type": "account", "id": "ACC0000000001"}
    db.add_all.assert_called_once()
    db.commit.assert_awaited_once()
    db.refresh.assert_awaited_once_with(session)
