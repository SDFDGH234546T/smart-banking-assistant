"""Unit tests for `chat_app.schemas.nlu`."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from chat_app.constants import TASK_TYPE_FREEZE_OR_LOSS, TASK_TYPE_QUERY_BALANCE
from chat_app.schemas import IntentItem, NLUResult, NLUSlots, TaskItem, TaskState


def test_intent_item_allows_unknown_task_type_for_parser_classification() -> None:
    item = IntentItem(
        category=" task_flow ",
        task_type="apply_loan",
        faq_topic="   ",
        confidence=0.85,
    )
    assert item.category == "task_flow"
    assert item.task_type == "apply_loan"
    assert item.faq_topic is None

    with pytest.raises(ValidationError):
        IntentItem(category="   ", confidence=0.5)

    with pytest.raises(ValidationError):
        IntentItem(category="chitchat", confidence=1.2)


def test_nlu_slots_normalizes_and_validates_whitelist() -> None:
    slots = NLUSlots(
        account_no=" ACC0000000001 ",
        target_status="frozen",
        transaction_type="transfer",
        currency_code=" cny ",
        limit=10,
        reason="   ",
    )
    assert slots.account_no == "ACC0000000001"
    assert slots.target_status == "frozen"
    assert slots.transaction_type == "transfer"
    assert slots.currency_code == "CNY"
    assert slots.reason is None

    with pytest.raises(ValidationError):
        NLUSlots(target_status="closed")

    with pytest.raises(ValidationError):
        NLUSlots(transaction_type="loan_repayment")

    with pytest.raises(ValidationError):
        NLUSlots(limit=51)


def test_nlu_result_defaults() -> None:
    result = NLUResult()
    assert result.intents == []
    assert result.slots == NLUSlots()
    assert result.ambiguity_reason is None


def test_task_item_and_task_state_validation() -> None:
    active = TaskItem(
        task_type=TASK_TYPE_FREEZE_OR_LOSS,
        stage="collecting_slots",
        slots={"account_no": "ACC0000000001"},
        missing_slots=["target_status", "reason"],
    )
    suspended = TaskItem(task_type=TASK_TYPE_QUERY_BALANCE)
    state = TaskState(active_task=active, suspended_tasks=[suspended])
    dumped = state.model_dump()
    assert dumped["active_task"]["task_type"] == TASK_TYPE_FREEZE_OR_LOSS
    assert len(dumped["suspended_tasks"]) == 1

    with pytest.raises(ValidationError):
        TaskItem(task_type="transfer_money")

    with pytest.raises(ValidationError):
        TaskItem(task_type=TASK_TYPE_QUERY_BALANCE, stage="completed")  # type: ignore[arg-type]
