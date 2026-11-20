"""NLU JSON cleaner, Pydantic validator, and anti-hallucination guardrail."""

from __future__ import annotations

import json
import re
from typing import Literal

from pydantic import BaseModel, ValidationError

from chat_app.constants import (
    FAQ_TOPICS,
    INTENT_CATEGORIES,
    INTENT_CATEGORY_KNOWLEDGE_QUERY,
    INTENT_CATEGORY_TASK_FLOW,
    NLU_CONFIDENCE_THRESHOLD,
    TASK_TYPES,
)
from chat_app.schemas import NLUResult

NLUFailureType = Literal[
    "ambiguous",
    "multi_intent_conflict",
    "out_of_scope",
    "invalid_schema",
]

_CLARIFICATION_REPLIES: dict[NLUFailureType, str] = {
    "multi_intent_conflict": (
        "检测到您同时提到了多项业务，为保障资金安全，请告诉我您希望先办理哪一项？"
    ),
    "ambiguous": (
        "抱歉，我没太明白您的意思。您可以让我帮您：\n"
        "1. 查询账户余额与状态\n"
        "2. 查询近期交易明细或单笔交易\n"
        "3. 申请账户冻结或挂失\n"
        "4. 咨询转账限额、手续费、产品或网点信息\n"
        "5. 转人工客服"
    ),
    "out_of_scope": (
        "抱歉，当前智能客服暂不支持该业务办理（如转账汇款、理财、贷款等）。"
        "如需进一步协助，您可以回复“转人工”由客服专员为您处理。"
    ),
    "invalid_schema": (
        "抱歉，刚才理解您的请求时出现了一点偏差，请您换一种说法再试一次，或回复“转人工”获取帮助。"
    ),
}

_CODE_FENCE_PATTERN = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


class NLUParseOutcome(BaseModel):
    """NLU 解析与风控校验结果。"""

    ok: bool
    result: NLUResult | None = None
    failure_type: NLUFailureType | None = None
    clarification_reply: str | None = None


def strip_markdown_code_fence(raw_text: str) -> str:
    """剥离 LLM 输出外层的 Markdown 代码块标记，并容错截取 JSON 主体。"""
    cleaned = raw_text.strip()
    cleaned = _CODE_FENCE_PATTERN.sub("", cleaned).strip()
    if not cleaned.startswith("{"):
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start != -1 and end != -1 and end > start:
            cleaned = cleaned[start : end + 1]
    return cleaned


def _fail(failure_type: NLUFailureType) -> NLUParseOutcome:
    return NLUParseOutcome(
        ok=False,
        result=None,
        failure_type=failure_type,
        clarification_reply=_CLARIFICATION_REPLIES[failure_type],
    )


def parse_nlu_response(
    raw_text: str,
    *,
    confidence_threshold: float = NLU_CONFIDENCE_THRESHOLD,
) -> NLUParseOutcome:
    """反序列化 LLM 输出并执行单意图、白名单与置信度风控校验。"""
    cleaned = strip_markdown_code_fence(raw_text)
    try:
        raw_obj = json.loads(cleaned)
        result = NLUResult.model_validate(raw_obj)
    except (json.JSONDecodeError, ValidationError, TypeError):
        return _fail("invalid_schema")

    # 1. 单意图唯一性防线：0 个意图视为模糊，多个意图视为冲突
    if len(result.intents) == 0:
        return _fail("ambiguous")
    if len(result.intents) > 1:
        return _fail("multi_intent_conflict")

    intent = result.intents[0]

    # 2. 顶层意图与任务白名单防线：拦截模型幻觉编造的未支持业务
    if intent.category not in INTENT_CATEGORIES:
        return _fail("out_of_scope")

    if intent.category == INTENT_CATEGORY_TASK_FLOW and intent.task_type not in TASK_TYPES:
        return _fail("out_of_scope")

    # 未知 faq_topic 统一归入 general 兜底查询，避免误拒合理咨询
    if intent.category == INTENT_CATEGORY_KNOWLEDGE_QUERY and (
        intent.faq_topic is None or intent.faq_topic not in FAQ_TOPICS
    ):
        intent.faq_topic = "general"

    # 3. 置信度阈值防线
    if intent.confidence < confidence_threshold:
        return _fail("ambiguous")

    return NLUParseOutcome(ok=True, result=result)
