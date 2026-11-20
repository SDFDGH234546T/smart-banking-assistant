"""S1 account and balance query handler."""

from __future__ import annotations

from typing import Any

from chat_app.clients.bank_client import BankClient
from chat_app.constants import (
    ACCOUNT_STATUS_ACTIVE,
    ACCOUNT_STATUS_CLOSED,
    ACCOUNT_STATUS_FROZEN,
    ACCOUNT_STATUS_LOST,
    ACCOUNT_STATUS_NORMAL,
)
from chat_app.orchestrator.task_manager import TaskManager
from chat_app.schemas.nlu import TaskState

_ACCOUNT_STATUS_LABELS: dict[str, str] = {
    ACCOUNT_STATUS_NORMAL: "正常",
    ACCOUNT_STATUS_ACTIVE: "正常",
    ACCOUNT_STATUS_FROZEN: "已冻结",
    ACCOUNT_STATUS_LOST: "已挂失",
    ACCOUNT_STATUS_CLOSED: "已销户",
}


def _append_resume_hint(reply_text: str, task_state: TaskState) -> str:
    """完成当前任务后若暂缓区非空，在回复末尾附带恢复提示。"""
    resumed = TaskManager.finish_active_task(task_state)
    hint = TaskManager.build_resume_hint(resumed)
    if hint:
        return f"{reply_text}\n\n{hint}"
    return reply_text


async def handle_account_query(
    sender_id: str,
    *,
    bank_client: BankClient,
    task_state: TaskState,
    slots: dict[str, Any],
) -> str:
    """处理 S1 账户与余额查询：优先查指定/缓存账户详情，否则汇总名下全部账户。"""
    account_no_raw = slots.get("account_no")
    account_no = str(account_no_raw).strip() if account_no_raw else ""

    if account_no:
        detail = await bank_client.get_account(sender_id, account_no)
        product = detail.get("account_product") or {}
        product_name = product.get("product_name") or "银行账户"
        status_code = str(detail.get("account_status", "")).strip()
        status_label = _ACCOUNT_STATUS_LABELS.get(status_code, status_code or "未知")
        balance = detail.get("balance_amount", "0.00")
        frozen = detail.get("frozen_amount", "0.00")

        reply = (
            f"账户 {account_no}（{product_name}）当前信息如下：\n"
            f"- 账户状态：{status_label}\n"
            f"- 账户余额：{balance}\n"
            f"- 冻结金额：{frozen}"
        )
        return _append_resume_hint(reply, task_state)

    data = await bank_client.list_customer_accounts(sender_id)
    accounts = data.get("list") or []
    if not accounts:
        return _append_resume_hint("您名下暂无银行账户记录。", task_state)

    lines = [f"您名下共有 {len(accounts)} 个银行账户："]
    for idx, acc in enumerate(accounts, start=1):
        acc_no = acc.get("account_no", "-")
        balance = acc.get("balance_amount", "0.00")
        currency = acc.get("currency_code", "CNY")
        product = acc.get("account_product") or {}
        product_name = product.get("product_name") or "银行账户"
        lines.append(f"{idx}. {product_name}（{acc_no}）：余额 {balance} {currency}")

    return _append_resume_hint("\n".join(lines), task_state)
