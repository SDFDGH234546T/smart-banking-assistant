"""S5 transfer-to-human support ticket handler."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from uuid import uuid4

from chat_app.clients.bank_client import BankClient
from chat_app.orchestrator.task_manager import TaskManager
from chat_app.schemas.nlu import TaskState


def _build_ticket_content(
    user_text: str,
    slots: dict[str, Any],
    history_messages: Sequence[dict[str, str]] | None,
) -> str:
    """结合槽位摘要与近期用户消息构造人工客服工单内容。"""
    summary_raw = slots.get("ticket_summary")
    summary = str(summary_raw).strip() if summary_raw else ""
    if summary:
        return summary

    recent_user_texts = [
        msg.get("text", "").strip()
        for msg in (history_messages or [])
        if msg.get("role") == "user" and msg.get("text", "").strip()
    ]
    if recent_user_texts:
        tail = " / ".join(recent_user_texts[-3:])
        return f"客户请求转人工协助，最近诉求：{tail}；本轮输入：{user_text}"
    return f"客户请求转人工协助：{user_text}"


async def handle_transfer_human(
    sender_id: str,
    *,
    user_text: str,
    bank_client: BankClient,
    task_state: TaskState,
    slots: dict[str, Any],
    history_messages: Sequence[dict[str, str]] | None = None,
) -> str:
    """创建中台客服工单并返回工单号，建单后立即清理任务且不锁死会话。"""
    existing_req = slots.get("request_no")
    request_no = (
        str(existing_req).strip()
        if isinstance(existing_req, str) and existing_req.strip()
        else f"TKTREQ{uuid4().hex[:14].upper()}"
    )
    slots["request_no"] = request_no

    ticket_content = _build_ticket_content(user_text, slots, history_messages)
    result = await bank_client.create_support_ticket(
        sender_id,
        request_no=request_no,
        ticket_title="智能客服转人工服务请求",
        ticket_content=ticket_content,
    )
    ticket_no = result.get("ticket_no", "-")

    # 建单后立即清空转人工任务，绝不锁死会话，用户可随时继续提问
    resumed = TaskManager.finish_active_task(task_state)
    hint = TaskManager.build_resume_hint(resumed)

    reply = (
        f"已为您创建人工客服工单，工单号：{ticket_no}，专员将尽快为您跟进处理。\n"
        "在等待期间，您仍可以随时向我咨询账户、交易或业务规则。"
    )
    return f"{reply}\n\n{hint}" if hint else reply
