"""Unit tests for object card branch handler."""

from __future__ import annotations

from chat_app.constants import (
    ACCOUNT_STATUS_FROZEN,
    TASK_STAGE_AWAITING_CONFIRM,
    TASK_STAGE_COLLECTING_SLOTS,
    TASK_TYPE_FREEZE_OR_LOSS,
    TASK_TYPE_QUERY_TRANSACTION_DETAIL,
)
from chat_app.orchestrator.handlers.object_card import handle_object_card
from chat_app.schemas.chat import ObjectPayload
from chat_app.schemas.nlu import TaskItem, TaskState


def test_object_card_without_active_task_caches_and_guides() -> None:
    """无运行中任务时，应更新 cached_object 并返回引导提示。"""
    card = ObjectPayload(type="account", id="ACC0000000001", title="活期储蓄卡")
    outcome = handle_object_card(card, TaskState(), cached_object=None)

    assert outcome.cached_object is not None
    assert outcome.cached_object["id"] == "ACC0000000001"
    assert outcome.intent_detail == "object_cached"
    assert outcome.reply_text is not None
    assert "ACC0000000001" in outcome.reply_text
    assert "余额" in outcome.reply_text


def test_object_card_fills_slot_and_transitions_to_confirm() -> None:
    """处于 collecting_slots 且类型匹配时，自动填槽并推进至下一阶段或待确认。"""
    state = TaskState(
        active_task=TaskItem(
            task_type=TASK_TYPE_FREEZE_OR_LOSS,
            stage=TASK_STAGE_COLLECTING_SLOTS,
            slots={"target_status": ACCOUNT_STATUS_FROZEN, "reason": "怀疑盗刷"},
            missing_slots=["account_no"],
        )
    )
    card = ObjectPayload(type="account", id="ACC0000000002")
    outcome = handle_object_card(card, state, cached_object=None)

    assert state.active_task is not None
    assert state.active_task.slots["account_no"] == "ACC0000000002"
    assert state.active_task.missing_slots == []
    assert state.active_task.stage == TASK_STAGE_AWAITING_CONFIRM
    assert "request_no" in state.active_task.slots
    assert outcome.reply_text is not None
    assert "请核对以下账户状态变更信息" in outcome.reply_text
    assert outcome.intent_detail == "object_slot_filled_awaiting_confirm"


def test_object_card_fills_query_task_marks_ready_to_execute() -> None:
    """非写操作任务因卡片填满槽位时，应返回 ready_to_execute_task。"""
    state = TaskState(
        active_task=TaskItem(
            task_type=TASK_TYPE_QUERY_TRANSACTION_DETAIL,
            stage=TASK_STAGE_COLLECTING_SLOTS,
            slots={},
            missing_slots=["transaction_no"],
        )
    )
    card = ObjectPayload(type="transaction", id="TXN00000001")
    outcome = handle_object_card(card, state, cached_object=None)

    assert outcome.ready_to_execute_task is not None
    assert outcome.ready_to_execute_task.slots["transaction_no"] == "TXN00000001"
    assert outcome.reply_text is None
    assert outcome.intent_detail == "object_slot_filled_ready"


def test_object_card_mismatch_preserves_state_and_clarifies() -> None:
    """对象类型不匹配或处于 awaiting_confirm 时，不得修改槽位与缓存。"""
    original_cache = {"type": "account", "id": "ACC0000000001"}
    state = TaskState(
        active_task=TaskItem(
            task_type=TASK_TYPE_QUERY_TRANSACTION_DETAIL,
            stage=TASK_STAGE_COLLECTING_SLOTS,
            slots={},
            missing_slots=["transaction_no"],
        )
    )
    wrong_card = ObjectPayload(type="account", id="ACC0000000099")
    outcome = handle_object_card(wrong_card, state, cached_object=original_cache)

    assert state.active_task is not None
    assert state.active_task.slots == {}
    assert state.active_task.missing_slots == ["transaction_no"]
    assert outcome.cached_object == original_cache
    assert outcome.intent_detail == "object_slot_mismatch"
    assert outcome.reply_text is not None
    assert "交易流水号" in outcome.reply_text

    # awaiting_confirm 状态下发卡片也应保持原状并澄清
    confirm_state = TaskState(
        active_task=TaskItem(
            task_type=TASK_TYPE_FREEZE_OR_LOSS,
            stage=TASK_STAGE_AWAITING_CONFIRM,
            slots={
                "account_no": "ACC0000000001",
                "target_status": ACCOUNT_STATUS_FROZEN,
                "reason": "遗失",
                "request_no": "REQ123",
            },
            missing_slots=[],
        )
    )
    confirm_outcome = handle_object_card(wrong_card, confirm_state, cached_object=original_cache)
    assert confirm_outcome.cached_object == original_cache
    assert confirm_outcome.intent_detail == "object_ignored_awaiting_confirm"
    assert confirm_outcome.reply_text is not None
    assert "确认" in confirm_outcome.reply_text
