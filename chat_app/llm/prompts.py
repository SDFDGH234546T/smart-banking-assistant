"""Centralized Prompt templates for NLU, S4 FAQ answers, and chitchat."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

from chat_app.schemas import ObjectPayload, TaskItem

_NLU_SYSTEM_PROMPT = """你是一个银行智能客服的意图识别与槽位抽取引擎。
请严格根据用户输入、历史对话和当前任务上下文，输出唯一的 JSON 对象（不要输出任何 Markdown 代码块以外的解释文字）。

输出 JSON Schema 必须严格如下：
{
  "intents": [
    {
      "category": "chitchat | knowledge_query | task_flow",
      "task_type": "query_balance | query_transactions | query_transaction_detail | freeze_or_loss_account | transfer_human | null",
      "faq_topic": "transfer_limit | fee_standard | account_product | branch | channel | currency | general | null",
      "confidence": 0.92
    }
  ],
  "slots": {
    "account_no": "ACC... 或 null",
    "transaction_no": "TXN... 或 null",
    "target_status": "frozen | lost | null",
    "reason": "挂失或冻结原因，否则 null",
    "transaction_type": "deposit | withdraw | transfer | consumption | refund | null",
    "currency_code": "CNY | USD 等币种编码，否则 null",
    "city": "城市名，否则 null",
    "limit": 10,
    "ticket_summary": "转人工诉求摘要，否则 null"
  },
  "ambiguity_reason": null
}

判断准则：
1. 仅针对【本轮用户输入】识别意图，严禁把【上下文】中的“当前活跃任务”或历史对话任务重复放入 intents 数组（例如：已有冻结任务但本轮用户说“先帮我查余额”时，intents 只能包含 query_balance 这 1 个意图，以便双区调度器挂起原任务）。
2. 仅当【本轮用户输入】一句话中同时提出多个彼此独立的业务诉求（如“查余额并冻结账户”）时，才将多个意图放入 intents 数组，由风控层处理。
3. 若用户咨询银行具体规则、限额、手续费、账户产品、支持渠道、币种或网点信息，归类为 knowledge_query 并选择最匹配的 faq_topic；若同时问及多个知识库主题（如“账户产品和渠道”），合并为 1 个 knowledge_query 意图（faq_topic 取主主题或 "general"）。若是“有什么业务可以办理”“你能做什么”“你好”等通用导览或寒暄，归类为 chitchat。
4. 若用户请求办理或查询具体账户/交易业务，归类为 task_flow 并给出对应 task_type；若用户请求超出上述 5 项范围（如转账汇款、购买理财、申请贷款），请保持 category="task_flow" 并在 task_type 填真实业务名（如 transfer_money/apply_loan），不要强行映射到不相干的任务。
5. 若当前存在 active_task 且处于 collecting_slots，而用户回复的是补充信息（如原因、账户号、“冻结”等），请延续该 task_type 并抽取对应槽位。
6. 未提及的槽位必须填 null，严禁编造账户号或交易号。"""


def build_nlu_messages(
    user_text: str,
    *,
    history_messages: Sequence[dict[str, str]] | None = None,
    active_task: TaskItem | None = None,
    cached_object: ObjectPayload | None = None,
) -> list[BaseMessage]:
    """构造 NLU 意图识别与槽位抽取的消息列表。"""
    context_lines: list[str] = []
    if active_task is not None:
        context_lines.append(
            f"当前活跃任务: task_type={active_task.task_type}, "
            f"stage={active_task.stage}, "
            f"missing_slots={active_task.missing_slots}, "
            f"filled_slots={json.dumps(active_task.slots, ensure_ascii=False)}"
        )
    if cached_object is not None:
        context_lines.append(
            f"当前会话焦点卡片: type={cached_object.type}, "
            f"id={cached_object.id}, title={cached_object.title or ''}"
        )
    if history_messages:
        recent_lines = [
            f"- {msg.get('role', 'user')}: {msg.get('text', '')}"
            for msg in history_messages
        ]
        context_lines.append("最近对话历史:\n" + "\n".join(recent_lines))

    context_block = "\n".join(context_lines) if context_lines else "无前置上下文"
    human_prompt = f"【上下文】\n{context_block}\n\n【本轮用户输入】\n{user_text}"
    return [
        SystemMessage(content=_NLU_SYSTEM_PROMPT),
        HumanMessage(content=human_prompt),
    ]


_FAQ_SYSTEM_PROMPT = """你是专业的手机银行智能客服，负责解答银行业务规则、限额、手续费、产品、渠道、币种与网点咨询。
必须严格遵守以下规则：
1. 只能依据下方提供的【中台实时查询结果】作答，严禁编造任何未在结果中出现的费率、限额、利率、网点电话或业务规则。
2. 若查询结果为空或未覆盖用户询问的具体问题，请诚实告知当前暂未查到相关标准，并建议用户回复“转人工”由专员协助。
3. 回复语气友好、条理清晰、精炼易读（使用中文）。"""


def build_faq_messages(
    user_text: str,
    *,
    faq_data: dict[str, Any],
    faq_topic: str | None = None,
) -> list[BaseMessage]:
    """构造 S4 中台规则实时问答 Prompt，将真实 foundation 数据注入上下文。"""
    serialized = json.dumps(faq_data, ensure_ascii=False, indent=2)
    topic_label = faq_topic or "general"
    human_prompt = (
        f"【咨询主题】{topic_label}\n\n"
        f"【中台实时查询结果】\n{serialized}\n\n"
        f"【用户问题】\n{user_text}"
    )
    return [
        SystemMessage(content=_FAQ_SYSTEM_PROMPT),
        HumanMessage(content=human_prompt),
    ]


_CHITCHAT_SYSTEM_PROMPT = """你是友好、专业的银行智能客服。
请用简洁、礼貌的中文回应用户的寒暄、感谢或能力咨询，并在合适时引导办理本系统支持的核心银行业务：
1. 查询银行账户与余额
2. 查询近期交易明细与单笔交易详情
3. 办理账户冻结或挂失
4. 咨询银行业务规则（转账限额、手续费、账户产品、渠道、币种、网点）
5. 转接人工客服创建工单
严禁编造上述范围之外的业务（如修改/重置密码、购买理财、申请贷款、转账汇款等），也不要编造任何账户余额或交易记录。"""


def build_chitchat_messages(
    user_text: str,
    *,
    active_task_name: str | None = None,
) -> list[BaseMessage]:
    """构造轻量闲聊与业务引导 Prompt。"""
    reminder = (
        f"\n（提示：用户当前仍有未完成的【{active_task_name}】任务，"
        "请在回复末尾温和提醒可继续提供信息或回复“取消”退出。）"
        if active_task_name
        else ""
    )
    return [
        SystemMessage(content=_CHITCHAT_SYSTEM_PROMPT + reminder),
        HumanMessage(content=user_text),
    ]
