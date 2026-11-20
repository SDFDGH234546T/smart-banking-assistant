"""Dual-zone task state manager (active task + suspended stack)."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from pydantic import ValidationError

from chat_app.constants import (
    SENSITIVE_WRITE_TASK_TYPES,
    TASK_STAGE_AWAITING_CONFIRM,
    TASK_STAGE_COLLECTING_SLOTS,
)
from chat_app.orchestrator.slot_templates import (
    OBJECT_TYPE_TO_SLOT,
    build_confirm_prompt,
    build_slot_prompt,
    compute_missing_slots,
    get_task_label,
)
from chat_app.schemas.chat import ObjectPayload
from chat_app.schemas.nlu import NLUSlots, TaskItem, TaskState


def extract_non_empty_slots(nlu_slots: NLUSlots | dict[str, Any] | None) -> dict[str, Any]:
    """提取非空有效槽位字典，避免 None 或纯空白值覆盖已有槽位。"""
    if nlu_slots is None:
        return {}
    raw = nlu_slots.model_dump() if isinstance(nlu_slots, NLUSlots) else dict(nlu_slots)
    cleaned: dict[str, Any] = {}
    for key, value in raw.items():
        if value is None:
            continue
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                continue
            cleaned[key] = stripped
        else:
            cleaned[key] = value
    return cleaned


class TaskManager:
    """双区任务调度管理器：负责 active_task 推进、suspended_tasks 压栈/恢复及幂等号生成。"""

    @staticmethod
    def load_state(raw_state: dict[str, Any] | None) -> TaskState:
        """从会话 JSON 安全恢复 TaskState，异常结构自动兜底为空状态。"""
        if not raw_state:
            return TaskState()
        try:
            return TaskState.model_validate(raw_state)
        except ValidationError:
            return TaskState()

    @staticmethod
    def dump_state(state: TaskState) -> dict[str, Any]:
        """将 TaskState 序列化为可持久化至 MySQL JSON 列的字典。"""
        return state.model_dump()

    @staticmethod
    def _apply_cached_object(
        slots: dict[str, Any],
        cached_object: dict[str, Any] | ObjectPayload | None,
    ) -> None:
        """仅在对应槽位缺失时融合会话缓存对象，确保用户本轮显式指定优先级更高。"""
        if cached_object is None:
            return
        if isinstance(cached_object, ObjectPayload):
            obj_type = cached_object.type
            obj_id = cached_object.id.strip()
        else:
            obj_type = str(cached_object.get("type", "")).strip()
            obj_id = str(cached_object.get("id", "")).strip()

        slot_name = OBJECT_TYPE_TO_SLOT.get(obj_type)
        if not slot_name or not obj_id:
            return
        existing = slots.get(slot_name)
        if existing is None or (isinstance(existing, str) and not existing.strip()):
            slots[slot_name] = obj_id

    @classmethod
    def start_or_update_task(
        cls,
        state: TaskState,
        task_type: str,
        new_slots: NLUSlots | dict[str, Any] | None = None,
        cached_object: dict[str, Any] | ObjectPayload | None = None,
    ) -> TaskItem:
        """启动新任务、同任务补槽，或在新任务切入时将原任务压入暂缓区栈。"""
        incoming_slots = extract_non_empty_slots(new_slots)

        if state.active_task is not None and state.active_task.task_type == task_type:
            task = state.active_task
            task.slots.update(incoming_slots)
            # 若用户在待确认阶段修改了参数，退回填槽重算以强制重新生成确认摘要
            if incoming_slots and task.stage == TASK_STAGE_AWAITING_CONFIRM:
                task.stage = TASK_STAGE_COLLECTING_SLOTS
        else:
            if state.active_task is not None:
                # 原活跃任务被不同新任务打断，压入暂缓栈等待后续自动恢复
                state.suspended_tasks.append(state.active_task)
            task = TaskItem(
                task_type=task_type,
                stage=TASK_STAGE_COLLECTING_SLOTS,
                slots=dict(incoming_slots),
            )
            state.active_task = task

        cls._apply_cached_object(task.slots, cached_object)
        task.missing_slots = compute_missing_slots(task.task_type, task.slots)
        if task.missing_slots:
            task.stage = TASK_STAGE_COLLECTING_SLOTS
        return task

    @staticmethod
    def is_sensitive_write_task(task_type: str) -> bool:
        """判断任务是否属于必须经过二次确认的敏感写操作。"""
        return task_type in SENSITIVE_WRITE_TASK_TYPES

    @staticmethod
    def prepare_confirmation(task: TaskItem) -> str:
        """将槽位齐全的敏感写任务置为 awaiting_confirm，并生成固定幂等 request_no。"""
        task.stage = TASK_STAGE_AWAITING_CONFIRM
        existing = task.slots.get("request_no")
        if isinstance(existing, str) and existing.strip():
            return existing.strip()
        request_no = f"REQ{uuid4().hex[:16].upper()}"
        task.slots["request_no"] = request_no
        return request_no

    @staticmethod
    def finish_active_task(state: TaskState) -> TaskItem | None:
        """完成或取消当前活跃任务，并在暂缓区非空时自动弹出最近一个任务恢复。"""
        state.active_task = None
        if state.suspended_tasks:
            resumed = state.suspended_tasks.pop()
            state.active_task = resumed
            return resumed
        return None

    @staticmethod
    def build_resume_hint(resumed_task: TaskItem | None) -> str | None:
        """为恢复的暂缓任务构造附加提示文案。"""
        if resumed_task is None:
            return None
        task_label = get_task_label(resumed_task.task_type)
        if resumed_task.stage == TASK_STAGE_AWAITING_CONFIRM:
            confirm_text = build_confirm_prompt(resumed_task.task_type, resumed_task.slots)
            return f"已为您恢复之前未完成的【{task_label}】办理。\n{confirm_text}"
        if resumed_task.missing_slots:
            slot_prompt = build_slot_prompt(resumed_task.task_type, resumed_task.missing_slots)
            return f"已为您恢复之前未完成的【{task_label}】办理，{slot_prompt}"
        return f"已为您恢复之前未完成的【{task_label}】办理，请继续提供相关指令。"
