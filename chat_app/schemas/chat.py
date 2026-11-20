"""External HTTP API request and response schemas aligned with `web/src/App.vue`."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from chat_app.constants import HISTORY_DIVIDER_TEXT


def _strip_or_none(value: str | None) -> str | None:
    """将纯空白字符串统一归一化为 None，避免空文本误通过非空校验。"""
    if value is None:
        return None
    stripped = value.strip()
    return stripped if stripped else None


class ObjectPayload(BaseModel):
    """前端右侧栏发送或机器人回传的对象卡片结构（账户 / 交易）。"""

    type: Literal["account", "transaction"]
    id: str = Field(..., min_length=1, description="账户号或交易流水号")
    title: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)

    @field_validator("id")
    @classmethod
    def _validate_id(cls, value: str) -> str:
        # 防止仅包含空格的字符串绕过 min_length=1 校验
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("object.id 不能为空")
        return cleaned


class ChatRequest(BaseModel):
    """`POST /api/chat` 请求体：支持纯文本或对象卡片输入。"""

    sender_id: str = Field(..., min_length=1, description="客户编号，如 CUS00000001")
    text: str | None = None
    object: ObjectPayload | None = None

    @field_validator("sender_id")
    @classmethod
    def _validate_sender_id(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("sender_id 不能为空")
        return cleaned

    @field_validator("text")
    @classmethod
    def _normalize_text(cls, value: str | None) -> str | None:
        return _strip_or_none(value)

    @model_validator(mode="after")
    def _ensure_text_or_object(self) -> ChatRequest:
        # 对话请求必须至少携带有效文本或对象卡片之一，避免空请求进入编排引擎
        if self.text is None and self.object is None:
            raise ValueError("text 与 object 至少需要提供一个")
        return self


class BotMessage(BaseModel):
    """`POST /api/chat` 响应中的单条机器人消息。"""

    text: str | None = None
    object: ObjectPayload | None = None

    @field_validator("text")
    @classmethod
    def _normalize_text(cls, value: str | None) -> str | None:
        return _strip_or_none(value)

    @model_validator(mode="after")
    def _ensure_content(self) -> BotMessage:
        if self.text is None and self.object is None:
            raise ValueError("BotMessage 必须包含 text 或 object")
        return self


class ChatResponse(BaseModel):
    """`POST /api/chat` 非流式同步响应体。"""

    messages: list[BotMessage] = Field(default_factory=list)


class HistoryMessage(BaseModel):
    """`GET /api/chat/history` 单条历史消息，支持 `divider` 分割线。"""

    role: Literal["user", "bot", "divider"]
    text: str | None = None
    object: ObjectPayload | None = None

    @field_validator("text")
    @classmethod
    def _normalize_text(cls, value: str | None) -> str | None:
        return _strip_or_none(value)

    @model_validator(mode="after")
    def _validate_by_role(self) -> HistoryMessage:
        if self.role == "divider":
            # 分割线仅用于 UI 隔断历史消息，不允许携带业务对象卡片
            if self.object is not None:
                raise ValueError("divider 消息不能包含 object")
            if self.text is None:
                self.text = HISTORY_DIVIDER_TEXT
            return self

        if self.text is None and self.object is None:
            raise ValueError("user/bot 历史消息必须包含 text 或 object")
        return self


class HistoryResponse(BaseModel):
    """`GET /api/chat/history` 响应体。"""

    messages: list[HistoryMessage] = Field(default_factory=list)
