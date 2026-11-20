"""NLU output and dual-zone task state Pydantic schemas."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from chat_app.constants import (
    TARGET_ACCOUNT_STATUSES,
    TASK_STAGE_COLLECTING_SLOTS,
    TASK_TYPES,
    TRANSACTION_TYPES,
)


def _strip_or_none(value: str | None) -> str | None:
    """将纯空白字符串归一化为 None，避免空串干扰后续槽位与意图判断。"""
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned if cleaned else None


class IntentItem(BaseModel):
    """单条 NLU 意图识别项。

    category/task_type/faq_topic 故意保持为 str / str | None，
    将白名单拦截留给 `llm/parser.py` 以精确区分 out_of_scope 与 invalid_schema。
    """

    category: str = Field(..., min_length=1)
    task_type: str | None = None
    faq_topic: str | None = None
    confidence: float = Field(..., ge=0.0, le=1.0)

    @field_validator("category")
    @classmethod
    def _validate_category(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("category 不能为空")
        return cleaned

    @field_validator("task_type", "faq_topic")
    @classmethod
    def _normalize_optional_str(cls, value: str | None) -> str | None:
        return _strip_or_none(value)


class NLUSlots(BaseModel):
    """NLU 槽位抽取结构。"""

    account_no: str | None = None
    transaction_no: str | None = None
    target_status: str | None = None
    reason: str | None = None
    transaction_type: str | None = None
    currency_code: str | None = None
    city: str | None = None
    limit: int | None = Field(default=None, ge=1, le=50)
    ticket_summary: str | None = None

    @field_validator(
        "account_no",
        "transaction_no",
        "reason",
        "city",
        "ticket_summary",
    )
    @classmethod
    def _normalize_text_slots(cls, value: str | None) -> str | None:
        return _strip_or_none(value)

    @field_validator("target_status")
    @classmethod
    def _validate_target_status(cls, value: str | None) -> str | None:
        cleaned = _strip_or_none(value)
        if cleaned is not None and cleaned not in TARGET_ACCOUNT_STATUSES:
            raise ValueError(f"不支持的账户目标状态: {cleaned}")
        return cleaned

    @field_validator("transaction_type")
    @classmethod
    def _validate_transaction_type(cls, value: str | None) -> str | None:
        cleaned = _strip_or_none(value)
        if cleaned is not None and cleaned not in TRANSACTION_TYPES:
            raise ValueError(f"不支持的交易类型过滤条件: {cleaned}")
        return cleaned

    @field_validator("currency_code")
    @classmethod
    def _normalize_currency_code(cls, value: str | None) -> str | None:
        cleaned = _strip_or_none(value)
        return cleaned.upper() if cleaned is not None else None


class NLUResult(BaseModel):
    """LLM 意图识别与槽位抽取的顶层 JSON 输出结构。"""

    intents: list[IntentItem] = Field(default_factory=list)
    slots: NLUSlots = Field(default_factory=NLUSlots)
    ambiguity_reason: str | None = None

    @field_validator("ambiguity_reason")
    @classmethod
    def _normalize_ambiguity_reason(cls, value: str | None) -> str | None:
        return _strip_or_none(value)


class TaskItem(BaseModel):
    """双区任务调度中的单个业务任务项。"""

    task_type: str
    stage: Literal["collecting_slots", "awaiting_confirm"] = TASK_STAGE_COLLECTING_SLOTS
    slots: dict[str, Any] = Field(default_factory=dict)
    missing_slots: list[str] = Field(default_factory=list)

    @field_validator("task_type")
    @classmethod
    def _validate_task_type(cls, value: str) -> str:
        # 仅允许白名单内的 MVP 任务进入状态机，防止未定义任务污染会话状态
        cleaned = value.strip()
        if cleaned not in TASK_TYPES:
            raise ValueError(f"非法任务类型: {cleaned}")
        return cleaned


class TaskState(BaseModel):
    """会话级双区任务状态（Active 活跃区 + Suspended 暂缓栈）。"""

    active_task: TaskItem | None = None
    suspended_tasks: list[TaskItem] = Field(default_factory=list)

