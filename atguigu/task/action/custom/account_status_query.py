"""
这个模块远程调用银行中台接口查询账户状态与余额信息
"""
from atguigu.conf.config import settings
from atguigu.domain.state import DialogueState
from atguigu.task.action.base import Action, ActionResult
from atguigu.utils import httpx_client

ACCOUNT_STATUS_LABELS = {
    "normal": "正常",
    "active": "正常",
    "frozen": "已冻结",
    "dormant": "休眠",
    "closed": "已销户",
    "restricted": "受限",
}


class AccountStatusAction(Action):
    name = "action_lookup_account_status"

    async def run(self, state: DialogueState) -> ActionResult:
        account_no = state.tasks.active.slots.get("account_no")
        base_url = settings.bank_api_base_url.rstrip("/")
        url = f"{base_url}/api/v1/accounts/{account_no}"
        response = await httpx_client.http_client.get(url)
        payload = response.json()
        data = payload.get("data") or {}

        if response.status_code != 200 or not data:
            return ActionResult(
                slots_update={
                    "account_status": "查询失败",
                    "account_summary": payload.get("message", "未查询到该账户信息。"),
                }
            )

        raw_status = data.get("account_status", "未知")
        status_label = ACCOUNT_STATUS_LABELS.get(raw_status, raw_status)
        balance = data.get("balance_amount", "未知")
        frozen = data.get("frozen_amount", "0.00")
        product = data.get("account_product") or {}
        product_name = product.get("product_name", "标准账户")

        summary = (
            f"账户产品：{product_name}，"
            f"账户余额：{balance} 元，"
            f"冻结金额：{frozen} 元。"
        )
        return ActionResult(
            slots_update={
                "account_status": status_label,
                "account_summary": summary,
            }
        )
