"""Unit tests for S3 account freeze / loss status-change handler."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from chat_app.constants import (
    ACCOUNT_STATUS_FROZEN,
    ACCOUNT_STATUS_LOST,
    TASK_STAGE_AWAITING_CONFIRM,
    TASK_STAGE_COLLECTING_SLOTS,
    TASK_TYPE_FREEZE_OR_LOSS,
    TASK_TYPE_QUERY_BALANCE,
)
from chat_app.orchestrator.handlers.status_change import (
    execute_status_change,
    handle_status_change_step,
)
from chat_app.schemas.nlu import TaskItem, TaskState


@pytest.mark.anyio
async def test_status_change_step_auto_fills_single_account_and_prepares_confirm() -> None:
    """名下仅 1 个账户且已提供状态与原因时，应自动带出账户号并进入二次确认。"""
    bank_client = MagicMock()
    bank_client.list_customer_accounts = AsyncMock(
        return_value={"list": [{"account_no": "ACC0000000001"}]}
    )
    task = TaskItem(
        task_type=TASK_TYPE_FREEZE_OR_LOSS,
        stage=TASK_STAGE_COLLECTING_SLOTS,
        slots={"target_status": ACCOUNT_STATUS_LOST, "reason": "银行卡遗失"},
        missing_slots=["account_no"],
    )
    state = TaskState(active_task=task)

    reply = await handle_status_change_step(
        "CUS00000001",
        bank_client=bank_client,
        task_state=state,
        task=task,
    )

    assert task.slots["account_no"] == "ACC0000000001"
    assert task.missing_slots == []
    assert task.stage == TASK_STAGE_AWAITING_CONFIRM
    assert "request_no" in task.slots
    assert "ACC0000000001" in reply
    assert "账户挂失" in reply
    assert "确认" in reply


@pytest.mark.anyio
async def test_execute_status_change_calls_api_and_resumes_suspended() -> None:
    """二次确认执行成功后应携带幂等 request_no 调中台并恢复暂缓任务。"""
    bank_client = MagicMock()
    bank_client.change_account_status = AsyncMock(
        return_value={"current_status": ACCOUNT_STATUS_FROZEN}
    )
    task = TaskItem(
        task_type=TASK_TYPE_FREEZE_OR_LOSS,
        stage=TASK_STAGE_AWAITING_CONFIRM,
        slots={
            "account_no": "ACC0000000001",
            "target_status": ACCOUNT_STATUS_FROZEN,
            "reason": "疑似异常交易",
            "request_no": "REQFIXED123",
        },
        missing_slots=[],
    )
    state = TaskState(
        active_task=task,
        suspended_tasks=[TaskItem(task_type=TASK_TYPE_QUERY_BALANCE)],
    )

    reply = await execute_status_change(
        "CUS00000001",
        bank_client=bank_client,
        task_state=state,
        task=task,
    )

    bank_client.change_account_status.assert_awaited_once_with(
        "CUS00000001",
        "ACC0000000001",
        request_no="REQFIXED123",
        target_status=ACCOUNT_STATUS_FROZEN,
        reason="疑似异常交易",
    )
    assert "已成功变更为【冻结】状态" in reply
    assert state.active_task is not None
    assert state.active_task.task_type == TASK_TYPE_QUERY_BALANCE
    assert "已为您恢复之前未完成的【账户与余额查询】办理" in reply
