"""Offline unit tests for SQLAlchemy 2.0 async engine and ORM models."""

from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.dialects import mysql
from sqlalchemy.schema import CreateIndex, CreateTable

from chat_app.db import engine as db_engine
from chat_app.db.models import (
    Base,
    ChatMessage,
    ChatSession,
    default_task_state,
    local_now,
)


def test_chat_session_schema_and_indexes() -> None:
    table = ChatSession.__table__
    assert table.name == "chat_session"

    expected_columns = {
        "id",
        "session_id",
        "sender_id",
        "status",
        "turn_count",
        "last_active_at",
        "cached_object_json",
        "task_state_json",
        "created_at",
        "updated_at",
    }
    assert expected_columns.issubset(set(table.columns.keys()))
    assert table.c.session_id.unique is True
    assert table.c.session_id.nullable is False
    assert table.c.cached_object_json.nullable is True
    assert table.c.task_state_json.nullable is False

    index_names = {idx.name for idx in table.indexes}
    assert "idx_chat_session_sender_status" in index_names


def test_chat_message_schema_and_indexes() -> None:
    table = ChatMessage.__table__
    assert table.name == "chat_message"

    expected_columns = {
        "id",
        "session_id",
        "sender_id",
        "turn_no",
        "role",
        "content_type",
        "text_content",
        "object_payload_json",
        "intent_category",
        "intent_detail",
        "created_at",
    }
    assert expected_columns.issubset(set(table.columns.keys()))
    assert table.c.text_content.nullable is True
    assert table.c.object_payload_json.nullable is True

    index_names = {idx.name for idx in table.indexes}
    assert "idx_chat_message_sender_id_id" in index_names
    assert "idx_chat_message_session_id_id" in index_names


def test_mysql_ddl_compilation() -> None:
    dialect = mysql.dialect()
    for model in (ChatSession, ChatMessage):
        ddl = str(CreateTable(model.__table__).compile(dialect=dialect))
        assert f"CREATE TABLE {model.__table__.name}" in ddl
        for idx in model.__table__.indexes:
            idx_ddl = str(CreateIndex(idx).compile(dialect=dialect))
            assert "CREATE INDEX" in idx_ddl


def test_default_task_state_is_isolated_and_local_now_is_naive() -> None:
    state1 = default_task_state()
    state2 = default_task_state()
    state1["active_task"] = {"task_type": "query_balance"}

    assert state2 == {"active_task": None, "suspended_tasks": []}
    now = local_now()
    assert now.tzinfo is None


@pytest.mark.anyio
async def test_init_db_and_dispose_engine_with_mock() -> None:
    mock_conn = MagicMock()
    mock_conn.run_sync = AsyncMock()

    mock_engine = MagicMock()

    @asynccontextmanager
    async def fake_begin():
        yield mock_conn

    mock_engine.begin = fake_begin
    mock_engine.dispose = AsyncMock()

    await db_engine.init_db(engine=mock_engine)
    mock_conn.run_sync.assert_awaited_once_with(Base.metadata.create_all)

    db_engine._engine = mock_engine
    db_engine._session_factory = MagicMock()
    await db_engine.dispose_engine()
    mock_engine.dispose.assert_awaited_once()
    assert db_engine._engine is None
    assert db_engine._session_factory is None


@pytest.mark.anyio
async def test_get_db_session_rolls_back_on_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_session = MagicMock()
    mock_session.rollback = AsyncMock()

    @asynccontextmanager
    async def fake_factory():
        yield mock_session

    monkeypatch.setattr(db_engine, "get_session_factory", lambda: fake_factory)

    gen = db_engine.get_db_session()
    yielded = await anext(gen)
    assert yielded is mock_session

    with pytest.raises(RuntimeError, match="boom"):
        await gen.athrow(RuntimeError("boom"))

    mock_session.rollback.assert_awaited_once()
