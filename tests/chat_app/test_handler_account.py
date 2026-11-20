"""Unit tests for S1 account and balance query handler."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from chat_app.constants import TASK_TYPE_FREEZE_OR_LOSS, TASK_TYPE_QUERY_BALANCE
from chat_app.orchestrator.handlers.account import handle_account_query
from chat_app.schemas.nlu import TaskItem, TaskState


@pytest.mark.anyio
async def test_account_query_single_account_detail() -> None:
    """指定或缓存 account_no 时应查询单账户详情并正确展示余额与冻结金额。"""
    bank_client = MagicMock()
    bank_client.get_account = AsyncMock(
        return_value={
            "account_status": "normal",
            "balance_amount": "12500.00",
            "frozen_amount": "200.00",
            "account_product": {"product_name": "活期储蓄账户"},
        }
    )
    state = TaskState(
        active_task=TaskItem(task_type=TASK_TYPE_QUERY_BALANCE),
        suspended_tasks=[
            TaskItem(
                task_type=TASK_TYPE_FREEZE_OR_LOSS,
                slots={"account_no": "ACC0000000001"},
                missing_slots=["target_status", "reason"],
            )
        ],
    )

    reply = await handle_account_query(
        "CUS00000001",
        bank_client=bank_client,
        task_state=state,
        slots={"account_no": "ACC0000000001"},
    )

    bank_client.get_account.assert_awaited_once_with("CUS00000001", "ACC0000000001")
    assert "ACC0000000001" in reply
    assert "12500.00" in reply
    assert "200.00" in reply
    assert "正常" in reply
    # 暂缓区原任务应自动恢复并在末尾提示
    assert state.active_task is not None
    assert state.active_task.task_type == TASK_TYPE_FREEZE_OR_LOSS
    assert "已为您恢复之前未完成的【账户冻结/挂失】办理" in reply


@pytest.mark.anyio
async def test_account_query_list_all_accounts() -> None:
    """未指定 account_no 时应查询客户名下账户列表并汇总输出。"""
    bank_client = MagicMock()
    bank_client.list_customer_accounts = AsyncMock(
        return_value={
            "list": [
                {
                    "account_no": "ACC0000000001",
                    "balance_amount": "1000.00",
                    "currency_code": "CNY",
                    "account_product": {"product_name": "活期储蓄"},
                },
                {
                    "account_no": "ACC0000000002",
                    "balance_amount": "500.00",
                    "currency_code": "USD",
                    "account_product": {"product_name": "美元账户"},
                },
            ]
        }
    )
    state = TaskState(active_task=TaskItem(task_type=TASK_TYPE_QUERY_BALANCE))

    reply = await handle_account_query(
        "CUS00000001",
        bank_client=bank_client,
        task_state=state,
        slots={},
    )

    bank_client.list_customer_accounts.assert_awaited_once_with("CUS00000001")
    assert "共有 2 个银行账户" in reply
    assert "ACC0000000001" in reply
    assert "500.00 USD" in reply
    assert state.active_task is None
