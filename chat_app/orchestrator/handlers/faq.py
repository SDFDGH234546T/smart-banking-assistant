"""S4 real-time banking rule FAQ handler (`knowledge_query`)."""

from __future__ import annotations

import asyncio
from typing import Any

from chat_app.clients.bank_client import BankClient
from chat_app.llm.client import LLMClient
from chat_app.llm.prompts import build_faq_messages


async def handle_faq_query(
    sender_id: str,
    *,
    user_text: str,
    faq_topic: str | None,
    slots: dict[str, Any],
    bank_client: BankClient,
    llm_client: LLMClient,
) -> str:
    """实时调用中台 foundation 接口并注入 Prompt，严禁编造费率与限额（不改动 active_task）。"""
    topic = faq_topic or "general"
    currency_code = slots.get("currency_code")
    city = slots.get("city")
    asks_both_limit_and_fee = "限额" in user_text and (
        "手续费" in user_text or "费率" in user_text
    )

    faq_data: dict[str, Any] = {}

    if asks_both_limit_and_fee:
        account_products, service_products = await asyncio.gather(
            bank_client.list_account_products(sender_id, currency_code=currency_code),
            bank_client.list_service_products(sender_id),
        )
        faq_data["account_products"] = account_products.get("list") or []
        faq_data["service_products"] = service_products.get("list") or []
    elif topic in ("transfer_limit", "account_product"):
        account_products = await bank_client.list_account_products(
            sender_id, currency_code=currency_code
        )
        faq_data["account_products"] = account_products.get("list") or []
    elif topic == "fee_standard":
        service_products = await bank_client.list_service_products(sender_id)
        faq_data["service_products"] = service_products.get("list") or []
    elif topic == "channel":
        channels = await bank_client.list_channels(sender_id)
        faq_data["channels"] = channels.get("list") or []
    elif topic == "currency":
        currencies = await bank_client.list_currencies(sender_id)
        faq_data["currencies"] = currencies.get("list") or []
    elif topic == "branch":
        branches = await bank_client.list_branches(sender_id, city=city)
        faq_data["branches"] = branches.get("list") or []
    else:
        # 泛化规则咨询时并发拉取核心产品、手续费与渠道数据，减少串行等待
        account_products, service_products, channels = await asyncio.gather(
            bank_client.list_account_products(sender_id, currency_code=currency_code),
            bank_client.list_service_products(sender_id),
            bank_client.list_channels(sender_id),
        )
        faq_data["account_products"] = account_products.get("list") or []
        faq_data["service_products"] = service_products.get("list") or []
        faq_data["channels"] = channels.get("list") or []

    messages = build_faq_messages(user_text, faq_data=faq_data, faq_topic=topic)
    return await llm_client.ainvoke(messages)
