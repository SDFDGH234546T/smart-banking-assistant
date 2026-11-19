"""
这个模块远程调用银行中台接口查询账户近期交易明细
"""
from atguigu.conf.config import settings
from atguigu.domain.state import DialogueState
from atguigu.task.action.base import Action, ActionResult
from atguigu.utils import httpx_client

TXN_TYPE_LABELS = {
    "deposit": "充值/存入",
    "withdraw": "提现/支取",
    "transfer": "转账",
    "consumption": "消费",
    "refund": "退款",
    "reversal": "冲正",
    "wealth_purchase": "理财申购",
    "wealth_redeem": "理财赎回",
    "loan_disbursement": "贷款放款",
    "loan_repayment": "贷款还款",
}

TXN_STATUS_LABELS = {
    "success": "成功",
    "failed": "失败",
    "pending": "处理中",
    "reversed": "已冲正",
}


class TransactionHistoryAction(Action):
    # 和yaml文件查询交易明细流程action步骤action属性值相同
    name = "action_lookup_transactions"

    async def run(self, state: DialogueState) -> ActionResult:
        account_no = state.tasks.active.slots.get("account_no")
        base_url = settings.bank_api_base_url.rstrip("/")
        url = f"{base_url}/api/v1/accounts/{account_no}/transactions"
        response = await httpx_client.http_client.get(url, params={"page_size": 5})
        payload = response.json()
        data = payload.get("data") or {}

        if response.status_code != 200 or not data:
            return ActionResult(
                slots_update={
                    "transaction_count": "0",
                    "transaction_summary": payload.get("message", "未查询到交易记录。"),
                }
            )

        total_count = data.get("total_count", 0)
        items = data.get("list") or []
        if not items:
            return ActionResult(
                slots_update={
                    "transaction_count": str(total_count),
                    "transaction_summary": "暂无近期交易记录。",
                }
            )

        lines: list[str] = ["最近交易记录如下："]
        for idx, item in enumerate(items[:5], start=1):
            txn_no = item.get("transaction_no", "未知")
            txn_type = TXN_TYPE_LABELS.get(
                item.get("transaction_type", ""),
                item.get("transaction_type", "未知"),
            )
            txn_status = TXN_STATUS_LABELS.get(
                item.get("transaction_status", ""),
                item.get("transaction_status", "未知"),
            )
            amount = item.get("transaction_amount", "0.00")
            currency = item.get("currency_code", "CNY")
            txn_at = item.get("transaction_at", "未知时间")
            lines.append(
                f"{idx}. [{txn_at}] {txn_type} {amount} {currency}（{txn_status}，交易号：{txn_no}）"
            )

        return ActionResult(
            slots_update={
                "transaction_count": str(total_count),
                "transaction_summary": "\n".join(lines),
            }
        )
