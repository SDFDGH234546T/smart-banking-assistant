"""Unit tests for S4 real-time banking rule FAQ handler."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from chat_app.constants import TASK_TYPE_FREEZE_OR_LOSS
from chat_app.orchestrator.handlers.faq import handle_faq_query
from chat_app.schemas.nlu import TaskItem, TaskState


@pytest.mark.anyio
async def test_faq_concurrent_limit_and_fee_query() -> None:
    """同时咨询限额与手续费时应并发调用 account-products 与 service-products。"""
    bank_client = MagicMock()
    bank_client.list_account_products = AsyncMock(
        return_value={"list": [{"product_name": "一类户", "daily_transfer_limit": "50000"}]}
    )
    bank_client.list_service_products = AsyncMock(
        return_value={"list": [{"service_name": "跨行转账", "fee_amount": "2.00"}]}
    )
    llm_client = MagicMock()
    llm_client.ainvoke = AsyncMock(return_value="一类户日转账限额 50000 元，跨行转账手续费 2.00 元。")

    # 模拟当前有活跃冻结任务，验证 FAQ 不会改动它
    state = TaskState(active_task=TaskItem(task_type=TASK_TYPE_FREEZE_OR_LOSS))

    reply = await handle_faq_query(
        "CUS00000001",
        user_text="转账限额和手续费怎么算？",
        faq_topic="transfer_limit",
        slots={"currency_code": "CNY"},
        bank_client=bank_client,
        llm_client=llm_client,
    )

    bank_client.list_account_products.assert_awaited_once_with(
        "CUS00000001", currency_code="CNY"
    )
    bank_client.list_service_products.assert_awaited_once_with("CUS00000001")
    llm_client.ainvoke.assert_awaited_once()
    assert "50000" in reply
    assert state.active_task is not None
    assert state.active_task.task_type == TASK_TYPE_FREEZE_OR_LOSS


@pytest.mark.anyio
async def test_faq_branch_query_passes_city_filter() -> None:
    """咨询网点时应调用 list_branches 并透传 city 过滤条件。"""
    bank_client = MagicMock()
    bank_client.list_branches = AsyncMock(
        return_value={"list": [{"branch_name": "北京朝阳支行", "service_phone": "010-88886666"}]}
    )
    llm_client = MagicMock()
    llm_client.ainvoke = AsyncMock(return_value="北京朝阳支行联系电话：010-88886666。")

    reply = await handle_faq_query(
        "CUS00000001",
        user_text="北京有哪些网点？",
        faq_topic="branch",
        slots={"city": "北京"},
        bank_client=bank_client,
        llm_client=llm_client,
    )

    bank_client.list_branches.assert_awaited_once_with("CUS00000001", city="北京")
    assert "010-88886666" in reply
