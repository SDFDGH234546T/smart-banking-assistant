"""S2 transaction list and single transaction detail handler."""

from __future__ import annotations

from typing import Any

from chat_app.clients.bank_client import BankClient
from chat_app.constants import (
    TASK_STAGE_COLLECTING_SLOTS,
    TASK_TYPE_QUERY_TRANSACTION_DETAIL,
)
from chat_app.orchestrator.task_manager import TaskManager
from chat_app.schemas.nlu import TaskState

_TXN_TYPE_LABELS: dict[str, str] = {
    "deposit": "存款",
    "withdraw": "取款",
    "transfer": "转账",
    "consumption": "消费",
    "refund": "退款",
}


def _append_resume_hint(reply_text: str, task_state: TaskState) -> str:
    """完成当前任务后若暂缓区非空，在回复末尾附带恢复提示。"""
    resumed = TaskManager.finish_active_task(task_state)
    hint = TaskManager.build_resume_hint(resumed)
    if hint:
        return f"{reply_text}\n\n{hint}"
    return reply_text


async def handle_transaction_detail(
    sender_id: str,
    *,
    bank_client: BankClient,
    task_state: TaskState,
    slots: dict[str, Any],
) -> str:
    """查询单笔交易详情与对账状态。"""
    transaction_no = str(slots.get("transaction_no", "")).strip()
    detail = await bank_client.get_transaction(sender_id, transaction_no)

    amount = detail.get("amount", "-")
    status = detail.get("transaction_status", "-")
    reconcile_status = detail.get("reconcile_status") or "暂无对账记录"
    channel_txn = detail.get("channel_transaction") or {}
    channel_no = channel_txn.get("channel_txn_no")

    lines = [
        f"交易 {transaction_no} 详情如下：",
        f"- 交易金额：{amount}",
        f"- 交易状态：{status}",
        f"- 对账状态：{reconcile_status}",
    ]
    if channel_no:
        lines.append(f"- 渠道流水号：{channel_no}")

    return _append_resume_hint("\n".join(lines), task_state)


async def handle_transaction_list(
    sender_id: str,
    *,
    bank_client: BankClient,
    task_state: TaskState,
    slots: dict[str, Any],
) -> str:
    """查询账户近期交易明细；未指定账户时单账户自动带出，多账户进入追问。"""
    account_no_raw = slots.get("account_no")
    account_no = str(account_no_raw).strip() if account_no_raw else ""

    if not account_no:
        acc_data = await bank_client.list_customer_accounts(sender_id)
        accounts = acc_data.get("list") or []
        if not accounts:
            return _append_resume_hint(
                "您名下暂无银行账户，无法查询交易明细。", task_state
            )
        if len(accounts) == 1:
            account_no = str(accounts[0].get("account_no", "")).strip()
            slots["account_no"] = account_no
        else:
            # 名下存在多个账户时退回 collecting_slots，列出账户供用户选择或发送卡片
            if task_state.active_task is not None:
                task_state.active_task.stage = TASK_STAGE_COLLECTING_SLOTS
                task_state.active_task.missing_slots = ["account_no"]
            options = [
                f"- {acc.get('account_no')}（{(acc.get('account_product') or {}).get('product_name') or '银行账户'}）"
                for acc in accounts
            ]
            return (
                "您名下有多个银行账户，请告知要查询哪一个账户的交易明细"
                "（也可直接从右侧栏发送账户卡片）：\n" + "\n".join(options)
            )

    txn_type = slots.get("transaction_type")
    limit_raw = slots.get("limit")
    page_size = int(limit_raw) if isinstance(limit_raw, int) and limit_raw > 0 else 10

    tx_data = await bank_client.list_account_transactions(
        sender_id,
        account_no,
        transaction_type=str(txn_type) if txn_type else None,
        page_size=page_size,
    )
    items = tx_data.get("list") or []
    if not items:
        return _append_resume_hint(
            f"账户 {account_no} 近期暂无符合条件的交易记录。", task_state
        )

    lines = [f"为您查到账户 {account_no} 最近 {len(items)} 笔交易明细："]
    for idx, item in enumerate(items, start=1):
        txn_no = item.get("transaction_no", "-")
        raw_type = str(item.get("transaction_type", ""))
        type_label = _TXN_TYPE_LABELS.get(raw_type, raw_type or "交易")
        # 兼容中台 account_transaction 表的 transaction_amount 字段
        amount = item.get("transaction_amount") or item.get("amount") or "0.00"
        currency = item.get("currency_code", "CNY")
        status = item.get("transaction_status", "-")
        txn_at = item.get("transaction_at") or ""
        time_part = f" | {txn_at}" if txn_at else ""
        lines.append(
            f"{idx}. [{type_label}] {amount} {currency}（{status}）| 流水号 {txn_no}{time_part}"
        )

    return _append_resume_hint("\n".join(lines), task_state)


async def handle_transaction_query(
    sender_id: str,
    *,
    task_type: str,
    bank_client: BankClient,
    task_state: TaskState,
    slots: dict[str, Any],
) -> str:
    """S2 统一分发入口：区分单笔交易详情与账户交易明细列表。"""
    if task_type == TASK_TYPE_QUERY_TRANSACTION_DETAIL:
        return await handle_transaction_detail(
            sender_id,
            bank_client=bank_client,
            task_state=task_state,
            slots=slots,
        )
    return await handle_transaction_list(
        sender_id,
        bank_client=bank_client,
        task_state=task_state,
        slots=slots,
    )
