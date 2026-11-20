"""Unit tests for `/api/chat` and `/api/chat/history` FastAPI routes."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from fastapi import FastAPI

from chat_app.config import Settings
from chat_app.constants import HISTORY_DIVIDER_TEXT
from chat_app.db.engine import get_db_session
from chat_app.routers.chat import router as chat_router
from chat_app.schemas.chat import BotMessage, ChatResponse


def _build_test_app(orchestrator_mock: MagicMock) -> FastAPI:
    app = FastAPI()
    app.include_router(chat_router)
    app.state.orchestrator = orchestrator_mock

    async def _override_db():
        yield MagicMock()

    app.dependency_overrides[get_db_session] = _override_db
    return app


@pytest.mark.anyio
async def test_post_chat_forwards_to_orchestrator() -> None:
    """POST /api/chat 应校验请求体并透传给 ChatOrchestrator.handle_chat。"""
    orchestrator = MagicMock()
    orchestrator.handle_chat = AsyncMock(
        return_value=ChatResponse(messages=[BotMessage(text="余额 1000.00 元")])
    )
    app = _build_test_app(orchestrator)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        resp = await client.post(
            "/api/chat",
            json={"sender_id": "CUS00000001", "text": "查余额"},
        )

    assert resp.status_code == 200
    assert resp.json() == {"messages": [{"text": "余额 1000.00 元", "object": None}]}
    orchestrator.handle_chat.assert_awaited_once()


@pytest.mark.anyio
async def test_get_chat_history_returns_empty_when_no_active_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """无有效活跃会话或已超时时，GET /api/chat/history 返回空列表且不追加 divider。"""
    monkeypatch.setattr(
        "chat_app.routers.chat.get_settings",
        lambda: Settings(DATABASE_URL="mysql+aiomysql://u:p@127.0.0.1:3306/db"),
    )
    monkeypatch.setattr(
        "chat_app.routers.chat.get_active_session_if_valid",
        AsyncMock(return_value=None),
    )
    app = _build_test_app(MagicMock())

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        resp = await client.get("/api/chat/history", params={"sender_id": "CUS00000001"})

    assert resp.status_code == 200
    assert resp.json() == {"messages": []}


@pytest.mark.anyio
async def test_get_chat_history_appends_divider_for_active_messages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """存在有效历史消息时，末尾必须追加 role=divider 分割线。"""
    monkeypatch.setattr(
        "chat_app.routers.chat.get_settings",
        lambda: Settings(DATABASE_URL="mysql+aiomysql://u:p@127.0.0.1:3306/db"),
    )
    monkeypatch.setattr(
        "chat_app.routers.chat.get_active_session_if_valid",
        AsyncMock(return_value=SimpleNamespace(session_id="SES001")),
    )
    monkeypatch.setattr(
        "chat_app.routers.chat.get_recent_messages",
        AsyncMock(
            return_value=[
                SimpleNamespace(
                    role="user",
                    text_content="你好",
                    object_payload_json=None,
                ),
                SimpleNamespace(
                    role="bot",
                    text_content="您好，请问有什么可以帮您？",
                    object_payload_json=None,
                ),
            ]
        ),
    )
    app = _build_test_app(MagicMock())

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        resp = await client.get("/api/chat/history", params={"sender_id": "CUS00000001"})

    assert resp.status_code == 200
    data = resp.json()
    assert len(data["messages"]) == 3
    assert data["messages"][-1] == {
        "role": "divider",
        "text": HISTORY_DIVIDER_TEXT,
        "object": None,
    }
