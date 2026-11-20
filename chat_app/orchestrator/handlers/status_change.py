"""S3 account freeze / loss status-change handler."""

from __future__ import annotations

from chat_app.clients.bank_client import BankClient
from chat_app.constants import TASK_STAGE_COLLECTING_SLOTS
from chat_app.orchestrator.slot_templates import (
    TARGET_STATUS_LABELS,
    build_confirm_prompt,
    build_slot_prompt,
    compute_missing_slots,
)
from chat_app.orchestrator.task_manager import TaskManager
from chat_app.schemas.nlu import TaskItem, TaskState


async def handle_status_change_step(
    sender_id: str,
    *,
    bank_client: BankClient,
    task_state: TaskState,
    task: TaskItem,
) -> str:
    """推进 S3 账户冻结/挂失填槽与二次确认准备阶段。"""
    # 若尚未指定账户号，尝试查询名下账户：仅 1 个时自动带出并在确认语中明示
    if "account_no" in task.missing_slots:
        acc_data = await bank_client.list_customer_accounts(sender_id)
        accounts = acc_data.get("list") or []
        if not accounts:
            resumed = TaskManager.finish_active_task(task_state)
            hint = TaskManager.build_resume_hint(resumed)
            msg = "您名下暂无可办理冻结或挂失的银行账户。"
            return f"{msg}\n\n{hint}" if hint else msg
        if len(accounts) == 1:
            only_acc = str(accounts[0].get("account_no", "")).strip()
            if only_acc:
                task.slots["account_no"] = only_acc
                task.missing_slots = compute_missing_slots(task.task_type, task.slots)

    if task.missing_slots:
        task.stage = TASK_STAGE_COLLECTING_SLOTS
        return build_slot_prompt(task.task_type, task.missing_slots)

    TaskManager.prepare_confirmation(task)
    return build_confirm_prompt(task.task_type, task.slots)


async def execute_status_change(
    sender_id: str,
    *,
    bank_client: BankClient,
    task_state: TaskState,
    task: TaskItem,
) -> str:
    """用户明确二次确认后，携带幂等 request_no 调用中台执行账户冻结或挂失。"""
    account_no = str(task.slots.get("account_no", "")).strip()
    target_status = str(task.slots.get("target_status", "")).strip()
    reason = str(task.slots.get("reason", "")).strip()
    request_no = TaskManager.prepare_confirmation(task)

    result = await bank_client.change_account_status(
        sender_id,
        account_no,
        request_no=request_no,
        target_status=target_status,
        reason=reason,
    )
    current_status = str(result.get("current_status", target_status))
    action_label = TARGET_STATUS_LABELS.get(current_status, current_status)

    reply = f"已完成办理：账户 {account_no} 已成功变更为【{action_label}】状态。"
    resumed = TaskManager.finish_active_task(task_state)
    hint = TaskManager.build_resume_hint(resumed)
    return f"{reply}\n\n{hint}" if hint else reply
