"""Unit tests for FastAPI app entry point, lifespan, /health, and error handler."""

from __future__ import annotations

from unittest.mock import AsyncMock

import httpx
import pytest

from chat_app.config import Settings
from chat_app.main import create_app


@pytest.mark.anyio
async def test_health_and_lifespan_wiring(monkeypatch: pytest.MonkeyPatch) -> None:
    """验证 lifespan 自动建表/释放资源与 /health 200 响应。"""
    init_db_mock = AsyncMock()
    dispose_mock = AsyncMock()
    monkeypatch.setattr(
        "chat_app.main.get_settings",
        lambda: Settings(DATABASE_URL="mysql+aiomysql://u:p@127.0.0.1:3306/db"),
    )
    monkeypatch.setattr("chat_app.main.init_db", init_db_mock)
    monkeypatch.setattr("chat_app.main.dispose_engine", dispose_mock)

    app = create_app()
    async with app.router.lifespan_context(app):
        assert hasattr(app.state, "orchestrator")
        assert hasattr(app.state, "http_client")
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            resp = await client.get("/health")
            assert resp.status_code == 200
            assert resp.json() == {"status": "ok", "service": "chat_app"}

    init_db_mock.assert_awaited_once()
    dispose_mock.assert_awaited_once()


@pytest.mark.anyio
async def test_unhandled_exception_returns_detail_json() -> None:
    """未捕获异常应返回 500 与标准 {"detail": "..."} 契约，不透传堆栈。"""
    app = create_app()

    @app.get("/boom")
    async def boom() -> None:
        raise RuntimeError("secret internal failure")

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        resp = await client.get("/boom")

    assert resp.status_code == 500
    body = resp.json()
    assert "detail" in body
    assert "secret internal failure" not in body["detail"]
