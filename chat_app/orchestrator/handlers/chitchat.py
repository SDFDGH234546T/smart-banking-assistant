"""Lightweight chitchat and business guidance handler."""

from __future__ import annotations

from chat_app.llm.client import LLMClient
from chat_app.llm.prompts import build_chitchat_messages
from chat_app.orchestrator.slot_templates import get_task_label
from chat_app.schemas.nlu import TaskState


async def handle_chitchat(
    *,
    user_text: str,
    task_state: TaskState,
    llm_client: LLMClient,
) -> str:
    """处理礼貌寒暄与自然业务引导，保持当前 active_task 不变。"""
    active_task_name = (
        get_task_label(task_state.active_task.task_type)
        if task_state.active_task is not None
        else None
    )
    messages = build_chitchat_messages(user_text, active_task_name=active_task_name)
    return await llm_client.ainvoke(messages)
