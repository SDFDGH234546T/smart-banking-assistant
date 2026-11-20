"""Async LLM client wrapper built on `langchain-openai`."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import httpx
from langchain_core.messages import BaseMessage
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from chat_app.config import get_settings


class LLMClientError(Exception):
    """大模型调用失败或超时时抛出的统一业务异常。"""

    def __init__(self, message: str, *, cause: Exception | None = None) -> None:
        self.message = message
        self.cause = cause
        super().__init__(message)


def _extract_text_content(content: Any) -> str:
    """兼容 LangChain AIMessage.content 为字符串或分段列表的提取逻辑。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
        return "".join(parts)
    return str(content) if content is not None else ""


class LLMClient:
    """轻量异步 LLM 客户端封装，支持在单测中直接注入 Mock 模型对象。"""

    def __init__(
        self,
        *,
        model: str | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
        timeout: float | None = None,
        temperature: float = 0.0,
        chat_model: Any | None = None,
    ) -> None:
        settings = get_settings()
        self._model_name = model or settings.LLM_MODEL
        self._base_url = (base_url or settings.LLM_BASE_URL).rstrip("/")
        self._api_key = api_key if api_key is not None else settings.LLM_API_KEY
        self._timeout = timeout if timeout is not None else settings.LLM_TIMEOUT_SECONDS
        self._temperature = temperature
        self._chat_model = chat_model

    def _get_or_create_model(self) -> Any:
        # 延迟实例化 ChatOpenAI，避免无密钥环境下仅构造客户端时提前失败
        if self._chat_model is not None:
            return self._chat_model
        if not self._api_key.strip():
            raise LLMClientError("未配置 LLM_API_KEY，无法调用大模型服务。")
        self._chat_model = ChatOpenAI(
            model=self._model_name,
            base_url=self._base_url,
            api_key=SecretStr(self._api_key),
            timeout=self._timeout,
            temperature=self._temperature,
        )
        return self._chat_model

    async def ainvoke(self, messages: Sequence[BaseMessage | dict[str, Any]]) -> str:
        """异步调用大模型并返回纯文本响应内容。"""
        model = self._get_or_create_model()
        try:
            response = await model.ainvoke(list(messages))
        except (TimeoutError, httpx.TimeoutException) as exc:
            raise LLMClientError("智能客服思考超时，请稍后再试。", cause=exc) from exc
        except LLMClientError:
            raise
        except Exception as exc:
            raise LLMClientError(
                "智能客服大模型服务暂时不可用，请稍后再试。",
                cause=exc,
            ) from exc

        content = getattr(response, "content", response)
        text = _extract_text_content(content).strip()
        if not text:
            raise LLMClientError("大模型返回了空响应。")
        return text
