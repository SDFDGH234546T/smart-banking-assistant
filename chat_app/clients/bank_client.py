"""Async HTTP client wrapping `app/` core banking APIs."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import httpx

from chat_app.config import get_settings
from chat_app.constants import (
    DEFAULT_CHANNEL_CODE,
    DEFAULT_OPERATOR_NO,
    DEFAULT_TICKET_RELATED_TYPE,
    DEFAULT_TICKET_TYPE,
)


class BankClientError(Exception):
    """调用银行业务中台失败时抛出的友好中文业务异常。"""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        error_code: str | None = None,
    ) -> None:
        self.message = message
        self.status_code = status_code
        self.error_code = error_code
        super().__init__(message)


def _translate_http_error(
    status_code: int,
    error_code: str | None,
    raw_message: str | None,
) -> str:
    """将中台 HTTP/业务错误码转译为对终端用户友好的中文提示。"""
    if status_code in (401, 403):
        return "身份校验未通过或无权访问该账户/交易信息，请核对客户编号后重试。"
    if status_code == 404:
        return "未查询到对应的客户、账户或交易记录，请核对编号是否正确。"
    if status_code == 409:
        return raw_message or "当前账户或业务状态不支持该操作，请核实后重试。"
    if status_code == 422:
        return "请求参数格式有误，请核对账户号或业务参数后重试。"
    if raw_message:
        return f"银行业务系统提示：{raw_message}"
    if error_code:
        return f"银行业务系统处理失败（{error_code}），请稍后重试。"
    return "银行业务系统暂时无法处理您的请求，请稍后重试。"


class BankClient:
    """中台 `app/` 异步 HTTP 客户端，复用外部注入的 `httpx.AsyncClient` 连接池。"""

    def __init__(
        self,
        http_client: httpx.AsyncClient,
        *,
        base_url: str | None = None,
        channel_code: str = DEFAULT_CHANNEL_CODE,
        timeout: float | None = None,
    ) -> None:
        settings = get_settings()
        self._client = http_client
        self._base_url = (base_url or settings.BANK_API_BASE_URL).rstrip("/")
        self._channel_code = channel_code
        self._timeout = (
            timeout if timeout is not None else settings.BANK_API_TIMEOUT_SECONDS
        )

    async def _request(
        self,
        method: str,
        path: str,
        *,
        sender_id: str,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> Any:
        url = f"{self._base_url}{path}"
        # 每次请求透传客户级鉴权头、渠道编码与唯一追踪 ID
        headers = {
            "Authorization": f"Bearer {sender_id}",
            "X-Channel-Code": self._channel_code,
            "X-Request-Id": uuid4().hex,
        }
        if extra_headers:
            headers.update(extra_headers)
        cleaned_params = (
            {k: v for k, v in params.items() if v is not None}
            if params is not None
            else None
        )

        try:
            response = await self._client.request(
                method,
                url,
                headers=headers,
                params=cleaned_params,
                json=json_body,
                timeout=self._timeout,
            )
        except httpx.TimeoutException as exc:
            raise BankClientError(
                "银行业务系统响应超时，请稍后重试。",
                status_code=504,
                error_code="TIMEOUT",
            ) from exc
        except httpx.RequestError as exc:
            raise BankClientError(
                "暂时无法连接银行业务系统，请稍后重试。",
                status_code=503,
                error_code="NETWORK_ERROR",
            ) from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise BankClientError(
                "银行业务系统返回了无法解析的响应格式。",
                status_code=response.status_code,
                error_code="INVALID_JSON",
            ) from exc

        if not isinstance(payload, dict):
            raise BankClientError(
                "银行业务系统响应结构异常。",
                status_code=response.status_code,
                error_code="INVALID_PAYLOAD",
            )

        biz_code = payload.get("code")
        # 中台统一以 HTTP 200 且 code == 0 表示成功；其余情况统一转译为 BankClientError
        if response.status_code >= 400 or biz_code != 0:
            raw_code = str(biz_code) if biz_code is not None else None
            raw_msg = payload.get("message")
            if not raw_msg and isinstance(payload.get("detail"), str):
                raw_msg = payload.get("detail")
            friendly_msg = _translate_http_error(
                response.status_code,
                raw_code,
                str(raw_msg) if raw_msg is not None else None,
            )
            raise BankClientError(
                friendly_msg,
                status_code=response.status_code,
                error_code=raw_code,
            )

        return payload.get("data")

    # --- S1: 账户与余额查询 ---

    async def list_customer_accounts(
        self,
        sender_id: str,
        *,
        account_status: str | None = None,
    ) -> dict[str, Any]:
        """查询客户名下账户列表（`GET /api/v1/customers/{customer_no}/accounts`）。"""
        data = await self._request(
            "GET",
            f"/api/v1/customers/{sender_id}/accounts",
            sender_id=sender_id,
            params={"account_status": account_status},
        )
        return data if isinstance(data, dict) else {"list": []}

    async def get_account(self, sender_id: str, account_no: str) -> dict[str, Any]:
        """查询单个账户详情（`GET /api/v1/accounts/{account_no}`）。"""
        data = await self._request(
            "GET",
            f"/api/v1/accounts/{account_no}",
            sender_id=sender_id,
        )
        return data if isinstance(data, dict) else {}

    # --- S2: 交易明细与单笔交易查询 ---

    async def list_account_transactions(
        self,
        sender_id: str,
        account_no: str,
        *,
        start_time: str | None = None,
        end_time: str | None = None,
        transaction_type: str | None = None,
        transaction_status: str | None = None,
        page_no: int = 1,
        page_size: int = 10,
    ) -> dict[str, Any]:
        """查询账户交易明细（`GET /api/v1/accounts/{account_no}/transactions`）。"""
        data = await self._request(
            "GET",
            f"/api/v1/accounts/{account_no}/transactions",
            sender_id=sender_id,
            params={
                "start_time": start_time,
                "end_time": end_time,
                "transaction_type": transaction_type,
                "transaction_status": transaction_status,
                "page_no": page_no,
                "page_size": page_size,
            },
        )
        return data if isinstance(data, dict) else {"list": []}

    async def get_transaction(
        self, sender_id: str, transaction_no: str
    ) -> dict[str, Any]:
        """查询单笔交易详情（`GET /api/v1/transactions/{transaction_no}`）。"""
        data = await self._request(
            "GET",
            f"/api/v1/transactions/{transaction_no}",
            sender_id=sender_id,
        )
        return data if isinstance(data, dict) else {}

    # --- S3: 账户冻结 / 挂失 ---

    async def change_account_status(
        self,
        sender_id: str,
        account_no: str,
        *,
        request_no: str,
        target_status: str,
        reason: str,
    ) -> dict[str, Any]:
        """变更账户状态（`POST /api/v1/accounts/{account_no}/status-changes`）。"""
        data = await self._request(
            "POST",
            f"/api/v1/accounts/{account_no}/status-changes",
            sender_id=sender_id,
            json_body={
                "request_no": request_no,
                "target_status": target_status,
                "reason": reason,
            },
        )
        return data if isinstance(data, dict) else {}

    # --- S4: 银行业务规则实时查询（foundation） ---

    async def list_account_products(
        self,
        sender_id: str,
        *,
        account_type: str | None = None,
        currency_code: str | None = None,
    ) -> dict[str, Any]:
        """查询账户产品与限额配置（`GET /api/v1/account-products`）。"""
        data = await self._request(
            "GET",
            "/api/v1/account-products",
            sender_id=sender_id,
            params={"account_type": account_type, "currency_code": currency_code},
        )
        return data if isinstance(data, dict) else {"list": []}

    async def list_service_products(
        self,
        sender_id: str,
        *,
        service_type: str | None = None,
        service_status: str | None = None,
    ) -> dict[str, Any]:
        """查询服务产品与手续费标准（`GET /api/v1/service-products`）。"""
        data = await self._request(
            "GET",
            "/api/v1/service-products",
            sender_id=sender_id,
            params={"service_type": service_type, "service_status": service_status},
        )
        return data if isinstance(data, dict) else {"list": []}

    async def list_channels(
        self,
        sender_id: str,
        *,
        channel_type: str | None = None,
        channel_status: str | None = None,
    ) -> dict[str, Any]:
        """查询可用业务渠道（`GET /api/v1/channels`）。"""
        data = await self._request(
            "GET",
            "/api/v1/channels",
            sender_id=sender_id,
            params={"channel_type": channel_type, "channel_status": channel_status},
        )
        return data if isinstance(data, dict) else {"list": []}

    async def list_currencies(
        self,
        sender_id: str,
        *,
        yn: int | None = None,
    ) -> dict[str, Any]:
        """查询可用币种列表（`GET /api/v1/currencies`）。"""
        data = await self._request(
            "GET",
            "/api/v1/currencies",
            sender_id=sender_id,
            params={"yn": yn},
        )
        return data if isinstance(data, dict) else {"list": []}

    async def list_branches(
        self,
        sender_id: str,
        *,
        branch_status: str | None = None,
        province: str | None = None,
        city: str | None = None,
    ) -> dict[str, Any]:
        """查询机构网点树（`GET /api/v1/branches`）。"""
        data = await self._request(
            "GET",
            "/api/v1/branches",
            sender_id=sender_id,
            params={
                "branch_status": branch_status,
                "province": province,
                "city": city,
            },
        )
        return data if isinstance(data, dict) else {"list": []}

    # --- S5: 转人工创建客服工单 ---

    async def create_support_ticket(
        self,
        sender_id: str,
        *,
        request_no: str,
        ticket_title: str,
        ticket_content: str,
        ticket_type: str = DEFAULT_TICKET_TYPE,
        related_type: str = DEFAULT_TICKET_RELATED_TYPE,
        related_id: int | None = None,
    ) -> dict[str, Any]:
        """创建客服工单（`POST /api/v1/support/tickets`）。"""
        data = await self._request(
            "POST",
            "/api/v1/support/tickets",
            sender_id=sender_id,
            extra_headers={"X-Operator-No": DEFAULT_OPERATOR_NO},
            json_body={
                "request_no": request_no,
                "customer_no": sender_id,
                "ticket_type": ticket_type,
                "ticket_title": ticket_title,
                "ticket_content": ticket_content,
                "related_type": related_type,
                "related_id": related_id,
            },
        )
        return data if isinstance(data, dict) else {}
