"""Unit tests for dual-zone TaskManager."""

from __future__ import annotations

from chat_app.constants import (
    ACCOUNT_STATUS_FROZEN,
    TASK_STAGE_AWAITING_CONFIRM,
    TASK_STAGE_COLLECTING_SLOTS,
    TASK_TYPE_FREEZE_OR_LOSS,
    TASK_TYPE_QUERY_BALANCE,
    TASK_TYPE_QUERY_TRANSACTION_DETAIL,
    TASK_TYPE_QUERY_TRANSACTIONS,
)
from chat_app.orchestrator.task_manager import TaskManager
from chat_app.schemas.nlu import NLUSlots, TaskState


def test_start_task_and_fuse_cached_object() -> None:
    """新任务启动时应自动融合 cached_object_json，且显式槽位优先于缓存。"""
    state = TaskState()
    cached = {"type": "account", "id": "ACC0000000001"}

    task = TaskManager.start_or_update_task(
        state,
        TASK_TYPE_FREEZE_OR_LOSS,
        new_slots=NLUSlots(target_status=ACCOUNT_STATUS_FROZEN),
        cached_object=cached,
    )
    assert task.slots["account_no"] == "ACC0000000001"
    assert task.slots["target_status"] == ACCOUNT_STATUS_FROZEN
    assert task.missing_slots == ["reason"]
    assert task.stage == TASK_STAGE_COLLECTING_SLOTS

    # 显式指定 account_no 时不应被 cached_object 覆盖
    state2 = TaskState()
    task2 = TaskManager.start_or_update_task(
        state2,
        TASK_TYPE_QUERY_TRANSACTIONS,
        new_slots={"account_no": "ACC0000000099"},
        cached_object=cached,
    )
    assert task2.slots["account_no"] == "ACC0000000099"
    assert task2.missing_slots == []


def test_suspend_and_auto_resume_stack() -> None:
    """新任务切入应将原任务压入 suspended_tasks，完成或取消后自动弹出恢复。"""
    state = TaskState()
    TaskManager.start_or_update_task(
        state,
        TASK_TYPE_FREEZE_OR_LOSS,
        new_slots={"account_no": "ACC0000000001"},
    )
    # 用户中途插话查询另一笔交易
    TaskManager.start_or_update_task(
        state,
        TASK_TYPE_QUERY_TRANSACTION_DETAIL,
        new_slots={},
    )
    assert state.active_task is not None
    assert state.active_task.task_type == TASK_TYPE_QUERY_TRANSACTION_DETAIL
    assert len(state.suspended_tasks) == 1
    assert state.suspended_tasks[0].task_type == TASK_TYPE_FREEZE_OR_LOSS

    # 完成当前任务后自动恢复原冻结任务
    resumed = TaskManager.finish_active_task(state)
    assert resumed is not None
    assert state.active_task is not None
    assert state.active_task.task_type == TASK_TYPE_FREEZE_OR_LOSS
    assert state.suspended_tasks == []

    hint = TaskManager.build_resume_hint(resumed)
    assert hint is not None
    assert "账户冻结/挂失" in hint


def test_same_task_slot_merge_and_idempotent_request_no() -> None:
    """同任务多轮补槽应保留已有槽位；进入待确认态应生成固定幂等 request_no。"""
    state = TaskState()
    TaskManager.start_or_update_task(
        state,
        TASK_TYPE_FREEZE_OR_LOSS,
        new_slots={"account_no": "ACC0000000001"},
    )
    task = TaskManager.start_or_update_task(
        state,
        TASK_TYPE_FREEZE_OR_LOSS,
        new_slots={"target_status": ACCOUNT_STATUS_FROZEN, "reason": "银行卡丢失"},
    )
    assert task.missing_slots == []
    assert TaskManager.is_sensitive_write_task(task.task_type)

    req1 = TaskManager.prepare_confirmation(task)
    req2 = TaskManager.prepare_confirmation(task)
    assert req1.startswith("REQ")
    assert req1 == req2
    assert task.stage == TASK_STAGE_AWAITING_CONFIRM


def test_load_and_dump_state_handles_invalid_payload() -> None:
    """非法或损坏的 JSON 状态应安全兜底为空 TaskState。"""
    state = TaskManager.load_state({"active_task": {"task_type": "invalid_task"}})
    assert state.active_task is None
    assert state.suspended_tasks == []

    TaskManager.start_or_update_task(state, TASK_TYPE_QUERY_BALANCE)
    dumped = TaskManager.dump_state(state)
    restored = TaskManager.load_state(dumped)
    assert restored.active_task is not None
    assert restored.active_task.task_type == TASK_TYPE_QUERY_BALANCE
