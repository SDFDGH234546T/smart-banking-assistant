"""Unit tests for ChatOrchestrator end-to-end orchestration pipeline."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from chat_app.config import Settings
from chat_app.constants import (
    ACCOUNT_STATUS_FROZEN,
    TASK_STAGE_AWAITING_CONFIRM,
    TASK_TYPE_FREEZE_OR_LOSS,
    TASK_TYPE_QUERY_BALANCE,
)
from chat_app.orchestrator.engine import ChatOrchestrator
from chat_app.schemas.chat import ChatRequest, ObjectPayload


def _make_settings() -> Settings:
    return Settings(
        DATABASE_URL="mysql+aiomysql://user:pass@127.0.0.1:3306/db",
        LLM_API_KEY="test-key",
    )


def _make_session(
    *,
    task_state_json: dict | None = None,
    cached_object_json: dict | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        session_id="SES001",
        sender_id="CUS00000001",
        turn_count=0,
        task_state_json=task_state_json or {"active_task": None, "suspended_tasks": []},
        cached_object_json=cached_object_json,
    )


@pytest.mark.anyio
async def test_engine_nlu_invalid_schema_retries_once_and_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """NLU 输出 invalid_schema 时应自动重试 1 次并在成功后完成业务查询。"""
    session = _make_session()
    monkeypatch.setattr(
        "chat_app.orchestrator.engine.get_or_create_active_session",
        AsyncMock(return_value=(session, False)),
    )
    monkeypatch.setattr(
        "chat_app.orchestrator.engine.get_recent_messages",
        AsyncMock(return_value=[]),
    )
    save_turn_mock = AsyncMock()
    monkeypatch.setattr("chat_app.orchestrator.engine.save_turn", save_turn_mock)

    valid_nlu = json.dumps(
        {
            "intents": [
                {
                    "category": "task_flow",
                    "task_type": TASK_TYPE_QUERY_BALANCE,
                    "faq_topic": None,
                    "confidence": 0.95,
                }
            ],
            "slots": {},
        }
    )
    llm_client = MagicMock()
    llm_client.ainvoke = AsyncMock(side_effect=["not a json", valid_nlu])

    bank_client = MagicMock()
    bank_client.list_customer_accounts = AsyncMock(
        return_value={
            "list": [
                {
                    "account_no": "ACC0000000001",
                    "balance_amount": "8888.00",
                    "currency_code": "CNY",
                    "account_product": {"product_name": "活期储蓄"},
                }
            ]
        }
    )

    orchestrator = ChatOrchestrator(
        bank_client=bank_client,
        llm_client=llm_client,
        settings=_make_settings(),
    )
    resp = await orchestrator.handle_chat(
        MagicMock(),
        ChatRequest(sender_id="CUS00000001", text="查一下账户余额"),
    )

    assert llm_client.ainvoke.await_count == 2
    assert "8888.00 CNY" in (resp.messages[0].text or "")
    save_turn_mock.assert_awaited_once()


@pytest.mark.anyio
async def test_engine_deterministic_cancel_and_confirm_intercept(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """待确认阶段输入“确认”应直接调中台写接口；输入“取消”应立即取消任务。"""
    confirm_session = _make_session(
        task_state_json={
            "active_task": {
                "task_type": TASK_TYPE_FREEZE_OR_LOSS,
                "stage": TASK_STAGE_AWAITING_CONFIRM,
                "slots": {
                    "account_no": "ACC0000000001",
                    "target_status": ACCOUNT_STATUS_FROZEN,
                    "reason": "卡丢失",
                    "request_no": "REQ999",
                },
                "missing_slots": [],
            },
            "suspended_tasks": [],
        }
    )
    monkeypatch.setattr(
        "chat_app.orchestrator.engine.get_or_create_active_session",
        AsyncMock(return_value=(confirm_session, False)),
    )
    monkeypatch.setattr(
        "chat_app.orchestrator.engine.get_recent_messages",
        AsyncMock(return_value=[]),
    )
    save_turn_mock = AsyncMock()
    monkeypatch.setattr("chat_app.orchestrator.engine.save_turn", save_turn_mock)

    llm_client = MagicMock()
    llm_client.ainvoke = AsyncMock()
    bank_client = MagicMock()
    bank_client.change_account_status = AsyncMock(
        return_value={"current_status": ACCOUNT_STATUS_FROZEN}
    )

    orchestrator = ChatOrchestrator(
        bank_client=bank_client,
        llm_client=llm_client,
        settings=_make_settings(),
    )

    # 1. 确认拦截：不调用 LLM
    resp_confirm = await orchestrator.handle_chat(
        MagicMock(),
        ChatRequest(sender_id="CUS00000001", text="确认"),
    )
    llm_client.ainvoke.assert_not_awaited()
    bank_client.change_account_status.assert_awaited_once()
    assert "已成功变更为【冻结】状态" in (resp_confirm.messages[0].text or "")

    # 2. 取消拦截：不调用 LLM
    cancel_session = _make_session(
        task_state_json={
            "active_task": {
                "task_type": TASK_TYPE_FREEZE_OR_LOSS,
                "stage": "collecting_slots",
                "slots": {},
                "missing_slots": ["account_no"],
            },
            "suspended_tasks": [],
        }
    )
    monkeypatch.setattr(
        "chat_app.orchestrator.engine.get_or_create_active_session",
        AsyncMock(return_value=(cancel_session, False)),
    )
    resp_cancel = await orchestrator.handle_chat(
        MagicMock(),
        ChatRequest(sender_id="CUS00000001", text="不想办理了"),
    )
    llm_client.ainvoke.assert_not_awaited()
    assert "已为您取消【账户冻结/挂失】办理" in (resp_cancel.messages[0].text or "")


@pytest.mark.anyio
async def test_engine_object_card_ready_executes_query_and_persists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """对象卡片填满非写操作槽位时，应直接执行对应查询并落库。"""
    session = _make_session(
        task_state_json={
            "active_task": {
                "task_type": "query_transaction_detail",
                "stage": "collecting_slots",
                "slots": {},
                "missing_slots": ["transaction_no"],
            },
            "suspended_tasks": [],
        }
    )
    monkeypatch.setattr(
        "chat_app.orchestrator.engine.get_or_create_active_session",
        AsyncMock(return_value=(session, False)),
    )
    monkeypatch.setattr(
        "chat_app.orchestrator.engine.get_recent_messages",
        AsyncMock(return_value=[]),
    )
    save_turn_mock = AsyncMock()
    monkeypatch.setattr("chat_app.orchestrator.engine.save_turn", save_turn_mock)

    bank_client = MagicMock()
    bank_client.get_transaction = AsyncMock(
        return_value={
            "transaction_status": "success",
            "amount": "199.00",
            "reconcile_status": "matched",
        }
    )
    llm_client = MagicMock()

    orchestrator = ChatOrchestrator(
        bank_client=bank_client,
        llm_client=llm_client,
        settings=_make_settings(),
    )
    resp = await orchestrator.handle_chat(
        MagicMock(),
        ChatRequest(
            sender_id="CUS00000001",
            object=ObjectPayload(type="transaction", id="TXN00000001"),
        ),
    )

    bank_client.get_transaction.assert_awaited_once_with("CUS00000001", "TXN00000001")
    assert "199.00" in (resp.messages[0].text or "")
    save_turn_kwargs = save_turn_mock.call_args.kwargs
    assert save_turn_kwargs["update_cached_object"] is True
    assert save_turn_kwargs["user_content_type"] == "object"
