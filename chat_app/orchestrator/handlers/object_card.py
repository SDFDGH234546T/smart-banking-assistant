"""Object card branch handler for `account` and `transaction` payloads."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from chat_app.constants import TASK_STAGE_AWAITING_CONFIRM, TASK_STAGE_COLLECTING_SLOTS
from chat_app.orchestrator.slot_templates import (
    OBJECT_TYPE_TO_SLOT,
    SLOT_LABELS,
    build_confirm_prompt,
    build_slot_prompt,
    compute_missing_slots,
    get_task_label,
)
from chat_app.orchestrator.task_manager import TaskManager
from chat_app.schemas.chat import ObjectPayload
from chat_app.schemas.nlu import TaskItem, TaskState

_OBJECT_TYPE_LABELS: dict[str, str] = {
    "account": "银行账户",
    "transaction": "交易记录",
}


@dataclass(slots=True)
class ObjectCardOutcome:
    """对象卡片分支处理结果。"""

    reply_text: str | None
    cached_object: dict[str, Any] | None
    intent_detail: str
    ready_to_execute_task: TaskItem | None = None


def _format_cached_card_reply(obj: ObjectPayload) -> str:
    """无运行中任务时，确认收到卡片并引导用户可执行操作。"""
    if obj.type == "account":
        title = f"（{obj.title}）" if obj.title else ""
        return (
            f"已收到您发送的账户卡片：{obj.id}{title}。\n"
            "您可以直接向我询问该账户的余额、近期交易明细，或申请办理账户冻结/挂失。"
        )

    title = f"（{obj.title}）" if obj.title else ""
    amount = obj.attributes.get("amount")
    amount_hint = f"，金额 {amount}" if amount is not None else ""
    return (
        f"已收到您发送的交易卡片：{obj.id}{title}{amount_hint}。\n"
        "您可以直接向我询问这笔交易的详情、状态，或转人工协助处理相关问题。"
    )


def handle_object_card(
    obj: ObjectPayload,
    task_state: TaskState,
    cached_object: dict[str, Any] | None,
) -> ObjectCardOutcome:
    """处理前端发送的 account / transaction 卡片，严格遵守双分流与不匹配保护。"""
    active_task = task_state.active_task

    # 分支 1：无运行中任务时，写入会话缓存并引导后续提问
    if active_task is None:
        return ObjectCardOutcome(
            reply_text=_format_cached_card_reply(obj),
            cached_object=obj.model_dump(),
            intent_detail="object_cached",
        )

    task_label = get_task_label(active_task.task_type)
    obj_label = _OBJECT_TYPE_LABELS.get(obj.type, obj.type)

    # 分支 2：处于待二次确认态时，不修改任务槽位与缓存，明确提示确认或取消
    if active_task.stage == TASK_STAGE_AWAITING_CONFIRM:
        return ObjectCardOutcome(
            reply_text=(
                f"当前正在为您办理【{task_label}】且已进入最终确认阶段，暂不接收新的{obj_label}卡片。\n"
                "请回复“确认”完成办理，或回复“取消”退出当前流程。"
            ),
            cached_object=cached_object,
            intent_detail="object_ignored_awaiting_confirm",
        )

    # 分支 3：处于 collecting_slots 时，校验对象类型是否匹配当前缺失槽位
    target_slot = OBJECT_TYPE_TO_SLOT.get(obj.type)
    if (
        active_task.stage != TASK_STAGE_COLLECTING_SLOTS
        or target_slot is None
        or target_slot not in active_task.missing_slots
    ):
        missing_labels = "、".join(
            SLOT_LABELS.get(name, name) for name in active_task.missing_slots
        )
        needed_hint = missing_labels if missing_labels else "必要信息"
        return ObjectCardOutcome(
            reply_text=(
                f"当前正在为您办理【{task_label}】，需要您提供【{needed_hint}】；"
                f"您发送的是{obj_label}卡片（{obj.id}），暂无法用于当前步骤。"
                "请补充所需信息，或回复“取消”退出当前办理。"
            ),
            cached_object=cached_object,
            intent_detail="object_slot_mismatch",
        )

    # 匹配成功：自动填槽、重算缺失槽位并同步更新焦点对象缓存
    active_task.slots[target_slot] = obj.id
    active_task.missing_slots = compute_missing_slots(active_task.task_type, active_task.slots)
    updated_cache = obj.model_dump()

    if active_task.missing_slots:
        return ObjectCardOutcome(
            reply_text=build_slot_prompt(active_task.task_type, active_task.missing_slots),
            cached_object=updated_cache,
            intent_detail="object_slot_filled_continue",
        )

    if TaskManager.is_sensitive_write_task(active_task.task_type):
        TaskManager.prepare_confirmation(active_task)
        return ObjectCardOutcome(
            reply_text=build_confirm_prompt(active_task.task_type, active_task.slots),
            cached_object=updated_cache,
            intent_detail="object_slot_filled_awaiting_confirm",
        )

    # 非写操作槽位已齐全，交由主编排器立即调用对应查询 Handler 执行
    return ObjectCardOutcome(
        reply_text=None,
        cached_object=updated_cache,
        intent_detail="object_slot_filled_ready",
        ready_to_execute_task=active_task,
    )
