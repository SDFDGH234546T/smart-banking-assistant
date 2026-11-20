"""Unit tests for S2 transaction list and detail handler."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from chat_app.constants import (
    TASK_STAGE_COLLECTING_SLOTS,
    TASK_TYPE_QUERY_TRANSACTION_DETAIL,
    TASK_TYPE_QUERY_TRANSACTIONS,
)
from chat_app.orchestrator.handlers.transaction import handle_transaction_query
from chat_app.schemas.nlu import TaskItem, TaskState


@pytest.mark.anyio
async def test_transaction_list_auto_fills_single_account() -> None:
    """未指定 account_no 且名下仅 1 个账户时，应自动带出并查询交易明细。"""
    bank_client = MagicMock()
    bank_client.list_customer_accounts = AsyncMock(
        return_value={"list": [{"account_no": "ACC0000000001"}]}
    )
    bank_client.list_account_transactions = AsyncMock(
        return_value={
            "list": [
                {
                    "transaction_no": "TXN00000001",
                    "transaction_type": "transfer",
                    "transaction_amount": "300.00",
                    "currency_code": "CNY",
                    "transaction_status": "success",
                    "transaction_at": "2026-11-20 10:00:00",
                }
            ]
        }
    )
    state = TaskState(active_task=TaskItem(task_type=TASK_TYPE_QUERY_TRANSACTIONS))

    reply = await handle_transaction_query(
        "CUS00000001",
        task_type=TASK_TYPE_QUERY_TRANSACTIONS,
        bank_client=bank_client,
        task_state=state,
        slots={"limit": 5},
    )

    bank_client.list_account_transactions.assert_awaited_once_with(
        "CUS00000001",
        "ACC0000000001",
        transaction_type=None,
        page_size=5,
    )
    assert "TXN00000001" in reply
    assert "300.00 CNY" in reply
    assert state.active_task is None


@pytest.mark.anyio
async def test_transaction_list_prompts_when_multiple_accounts() -> None:
    """名下存在多个账户且未指定时，应退回 collecting_slots 并列出账户供选择。"""
    bank_client = MagicMock()
    bank_client.list_customer_accounts = AsyncMock(
        return_value={
            "list": [
                {"account_no": "ACC0000000001", "account_product": {"product_name": "一类户"}},
                {"account_no": "ACC0000000002", "account_product": {"product_name": "二类户"}},
            ]
        }
    )
    state = TaskState(active_task=TaskItem(task_type=TASK_TYPE_QUERY_TRANSACTIONS))

    reply = await handle_transaction_query(
        "CUS00000001",
        task_type=TASK_TYPE_QUERY_TRANSACTIONS,
        bank_client=bank_client,
        task_state=state,
        slots={},
    )

    assert "多个银行账户" in reply
    assert "ACC0000000001" in reply
    assert "ACC0000000002" in reply
    assert state.active_task is not None
    assert state.active_task.stage == TASK_STAGE_COLLECTING_SLOTS
    assert state.active_task.missing_slots == ["account_no"]


@pytest.mark.anyio
async def test_transaction_detail_query() -> None:
    """单笔交易查询应调用 get_transaction 并输出金额、状态与对账结果。"""
    bank_client = MagicMock()
    bank_client.get_transaction = AsyncMock(
        return_value={
            "transaction_status": "success",
            "amount": "88.50",
            "reconcile_status": "matched",
            "channel_transaction": {"channel_txn_no": "CHN999"},
        }
    )
    state = TaskState(
        active_task=TaskItem(
            task_type=TASK_TYPE_QUERY_TRANSACTION_DETAIL,
            slots={"transaction_no": "TXN00000002"},
        )
    )

    reply = await handle_transaction_query(
        "CUS00000001",
        task_type=TASK_TYPE_QUERY_TRANSACTION_DETAIL,
        bank_client=bank_client,
        task_state=state,
        slots={"transaction_no": "TXN00000002"},
    )

    assert "TXN00000002" in reply
    assert "88.50" in reply
    assert "matched" in reply
    assert "CHN999" in reply
    assert state.active_task is None
