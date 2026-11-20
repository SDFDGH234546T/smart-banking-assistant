"""Unit tests for lightweight chitchat handler."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from chat_app.constants import TASK_TYPE_FREEZE_OR_LOSS
from chat_app.orchestrator.handlers.chitchat import handle_chitchat
from chat_app.schemas.nlu import TaskItem, TaskState


@pytest.mark.anyio
async def test_chitchat_preserves_active_task_and_passes_reminder() -> None:
    """闲聊响应时必须保持 active_task 不变，并在存在任务时注入轻提醒。"""
    llm_client = MagicMock()
    llm_client.ainvoke = AsyncMock(return_value="不客气！如需继续办理账户冻结/挂失，请提供原因。")
    state = TaskState(
        active_task=TaskItem(
            task_type=TASK_TYPE_FREEZE_OR_LOSS,
            missing_slots=["reason"],
        )
    )

    reply = await handle_chitchat(
        user_text="谢谢你",
        task_state=state,
        llm_client=llm_client,
    )

    llm_client.ainvoke.assert_awaited_once()
    sent_messages = llm_client.ainvoke.call_args.args[0]
    assert "账户冻结/挂失" in sent_messages[0].content
    assert "谢谢" in reply or "冻结" in reply
    assert state.active_task is not None
    assert state.active_task.task_type == TASK_TYPE_FREEZE_OR_LOSS
