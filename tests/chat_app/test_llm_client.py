"""Unit tests for `chat_app.llm.client`."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from langchain_core.messages import HumanMessage

from chat_app.llm import LLMClient, LLMClientError


@pytest.fixture
def _env_db(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "mysql+aiomysql://root:pass@127.0.0.1:3306/test")


@pytest.mark.anyio
async def test_llm_client_ainvoke_success_with_str_and_list(_env_db: None) -> None:
    class _FakeModel:
        def __init__(self, content: Any) -> None:
            self._content = content
            self.received: list[Any] = []

        async def ainvoke(self, messages: list[Any]) -> Any:
            self.received = messages
            return SimpleNamespace(content=self._content)

    fake_str = _FakeModel("  你好，请问有什么可以帮您？  ")
    client_str = LLMClient(chat_model=fake_str)
    reply = await client_str.ainvoke([HumanMessage(content="你好")])
    assert reply == "你好，请问有什么可以帮您？"
    assert len(fake_str.received) == 1

    fake_list = _FakeModel([{"text": '{"ok": '}, {"text": "true}"}])
    client_list = LLMClient(chat_model=fake_list)
    assert await client_list.ainvoke([HumanMessage(content="test")]) == '{"ok": true}'


@pytest.mark.anyio
async def test_llm_client_requires_api_key_when_no_mock_injected(
    monkeypatch: pytest.MonkeyPatch, _env_db: None
) -> None:
    monkeypatch.setenv("LLM_API_KEY", "")
    client = LLMClient(api_key="")
    with pytest.raises(LLMClientError, match="LLM_API_KEY"):
        await client.ainvoke([HumanMessage(content="你好")])


@pytest.mark.anyio
async def test_llm_client_wraps_timeout_and_runtime_errors(_env_db: None) -> None:
    class _TimeoutModel:
        async def ainvoke(self, messages: list[Any]) -> Any:
            raise httpx.ReadTimeout("timeout")

    class _BrokenModel:
        async def ainvoke(self, messages: list[Any]) -> Any:
            raise RuntimeError("upstream 500")

    client_timeout = LLMClient(chat_model=_TimeoutModel())
    with pytest.raises(LLMClientError, match="超时"):
        await client_timeout.ainvoke([HumanMessage(content="hi")])

    client_broken = LLMClient(chat_model=_BrokenModel())
    with pytest.raises(LLMClientError, match="暂时不可用"):
        await client_broken.ainvoke([HumanMessage(content="hi")])
