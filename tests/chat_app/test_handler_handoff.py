"""Unit tests for S5 transfer-to-human ticket handler."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from chat_app.constants import TASK_TYPE_TRANSFER_HUMAN
from chat_app.orchestrator.handlers.handoff import handle_transfer_human
from chat_app.schemas.nlu import TaskItem, TaskState


@pytest.mark.anyio
async def test_transfer_human_creates_ticket_and_clears_task() -> None:
    """转人工建单应调用 create_support_ticket、返回工单号并清空任务（不锁死会话）。"""
    bank_client = MagicMock()
    bank_client.create_support_ticket = AsyncMock(
        return_value={"ticket_no": "TKT202611200001", "ticket_status": "open"}
    )
    state = TaskState(active_task=TaskItem(task_type=TASK_TYPE_TRANSFER_HUMAN))

    reply = await handle_transfer_human(
        "CUS00000001",
        user_text="转人工处理一下跨境汇款限额问题",
        bank_client=bank_client,
        task_state=state,
        slots={"ticket_summary": "客户咨询跨境汇款限额需要人工专员协助"},
        history_messages=[{"role": "user", "text": "跨境汇款有限额吗"}],
    )

    bank_client.create_support_ticket.assert_awaited_once()
    call_kwargs = bank_client.create_support_ticket.call_args.kwargs
    assert call_kwargs["ticket_content"] == "客户咨询跨境汇款限额需要人工专员协助"
    assert call_kwargs["request_no"].startswith("TKTREQ")
    assert "TKT202611200001" in reply
    assert "随时向我咨询" in reply
    assert state.active_task is None
