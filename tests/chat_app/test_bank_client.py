"""Unit tests for `chat_app.clients.bank_client`."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from chat_app.clients import BankClient, BankClientError


@pytest.fixture
def _env_db(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "mysql+aiomysql://root:pass@127.0.0.1:3306/test")


@pytest.mark.anyio
async def test_bank_client_headers_and_read_endpoints(_env_db: None) -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        if request.url.path == "/api/v1/customers/CUS00000001/accounts":
            return httpx.Response(
                200,
                json={"code": 0, "message": "ok", "data": {"list": [{"account_no": "ACC1"}]}},
            )
        if request.url.path == "/api/v1/accounts/ACC1/transactions":
            return httpx.Response(
                200,
                json={"code": 0, "message": "ok", "data": {"list": [], "total_count": 0}},
            )
        return httpx.Response(200, json={"code": 0, "message": "ok", "data": {"list": []}})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = BankClient(http_client, base_url="http://127.0.0.1:8000")
        accounts = await client.list_customer_accounts("CUS00000001")
        txns = await client.list_account_transactions(
            "CUS00000001", "ACC1", transaction_type="transfer", page_size=5
        )
        await client.list_account_products("CUS00000001", currency_code="CNY")
        await client.list_service_products("CUS00000001", service_type="transfer")
        await client.list_channels("CUS00000001")
        await client.list_currencies("CUS00000001", yn=1)
        await client.list_branches("CUS00000001", city="北京")

    assert accounts["list"][0]["account_no"] == "ACC1"
    assert txns["total_count"] == 0
    assert len(captured) == 7

    first_req = captured[0]
    assert first_req.headers["Authorization"] == "Bearer CUS00000001"
    assert first_req.headers["X-Channel-Code"] == "MOBILE_BANK"
    assert len(first_req.headers["X-Request-Id"]) > 0
    assert "account_status" not in first_req.url.params

    txn_req = captured[1]
    assert txn_req.url.params["transaction_type"] == "transfer"
    assert txn_req.url.params["page_size"] == "5"


@pytest.mark.anyio
async def test_bank_client_write_endpoints_payload(_env_db: None) -> None:
    bodies: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content.decode("utf-8")))
        if request.url.path.endswith("/status-changes"):
            return httpx.Response(
                200,
                json={"code": 0, "message": "ok", "data": {"current_status": "frozen"}},
            )
        return httpx.Response(
            200,
            json={"code": 0, "message": "ok", "data": {"ticket_no": "TKT001"}},
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = BankClient(http_client, base_url="http://127.0.0.1:8000")
        res1 = await client.change_account_status(
            "CUS00000001",
            "ACC0000000001",
            request_no="REQ-1",
            target_status="frozen",
            reason="卡片遗失",
        )
        res2 = await client.create_support_ticket(
            "CUS00000001",
            request_no="REQ-2",
            ticket_title="客户咨询",
            ticket_content="申请人工协助",
        )

    assert res1["current_status"] == "frozen"
    assert res2["ticket_no"] == "TKT001"
    assert bodies[0] == {
        "request_no": "REQ-1",
        "target_status": "frozen",
        "reason": "卡片遗失",
    }
    assert bodies[1]["customer_no"] == "CUS00000001"
    assert bodies[1]["ticket_type"] == "general_inquiry"
    assert bodies[1]["related_type"] == "none"


@pytest.mark.anyio
async def test_bank_client_error_translation(_env_db: None) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/ACC_403"):
            return httpx.Response(403, json={"code": "FORBIDDEN", "message": "forbidden"})
        if request.url.path.endswith("/ACC_404"):
            return httpx.Response(404, json={"code": "NOT_FOUND", "message": "not found"})
        return httpx.Response(200, json={"code": 40001, "message": "账户状态异常"})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = BankClient(http_client, base_url="http://127.0.0.1:8000")

        with pytest.raises(BankClientError) as exc_403:
            await client.get_account("CUS00000001", "ACC_403")
        assert exc_403.value.status_code == 403
        assert "无权访问" in exc_403.value.message

        with pytest.raises(BankClientError) as exc_404:
            await client.get_account("CUS00000001", "ACC_404")
        assert exc_404.value.status_code == 404
        assert "未查询到" in exc_404.value.message

        with pytest.raises(BankClientError) as exc_biz:
            await client.get_transaction("CUS00000001", "TXN_BIZ")
        assert exc_biz.value.error_code == "40001"
        assert "账户状态异常" in exc_biz.value.message


@pytest.mark.anyio
async def test_bank_client_timeout_and_network_errors(_env_db: None) -> None:
    def timeout_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timeout", request=request)

    transport = httpx.MockTransport(timeout_handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = BankClient(http_client, base_url="http://127.0.0.1:8000")
        with pytest.raises(BankClientError) as exc_info:
            await client.get_account("CUS00000001", "ACC1")
        assert exc_info.value.status_code == 504
        assert exc_info.value.error_code == "TIMEOUT"
