"""
这个模块类似TaskHandler里面action
发送远程调用，调用银行中台接口得到数据
"""
import asyncio
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass

from atguigu.conf.config import settings
from atguigu.domain.message import UserMessage
from atguigu.domain.state import DialogueState
from atguigu.utils import httpx_client


# 定义类封装最终结果
@dataclass
class KnowledgeChunk:
    content: str = ""


# 创建基类，定义属性和抽象方法
class KnowledgeProvider(ABC):
    # 属性
    provider_id: str = ""

    # 抽象方法
    @abstractmethod
    async def execute(self, state: DialogueState,
                      user_message: UserMessage) -> list[KnowledgeChunk]:
        pass


# 单笔交易信息咨询  api.transaction
class ApiTransactionProvider(KnowledgeProvider):
    provider_id = "api.transaction"

    # 远程调用
    async def execute(self, state: DialogueState,
                      user_message: UserMessage) -> list[KnowledgeChunk]:
        if not state.shared.focused_object:
            return [KnowledgeChunk(content="未指定当前咨询的交易流水号")]
        transaction_no = state.shared.focused_object.id
        base_url = settings.bank_api_base_url.rstrip("/")
        url = f"{base_url}/api/v1/transactions/{transaction_no}"
        response = await httpx_client.http_client.get(url)
        payload = response.json()
        data = payload.get("data") or {"message": payload.get("message", "未查询到交易详情")}
        chunk = json.dumps(data, ensure_ascii=False)
        return [KnowledgeChunk(content=chunk)]


# 银行账户信息咨询  api.account
class ApiAccountProvider(KnowledgeProvider):
    provider_id = "api.account"

    async def execute(self, state: DialogueState,
                      user_message: UserMessage) -> list[KnowledgeChunk]:
        if not state.shared.focused_object:
            return [KnowledgeChunk(content="未指定当前咨询的银行账户号")]
        account_no = state.shared.focused_object.id
        base_url = settings.bank_api_base_url.rstrip("/")
        # 调用查询账户详情接口
        account_url = f"{base_url}/api/v1/accounts/{account_no}"
        # 调用查询账户近期交易明细接口
        txns_url = f"{base_url}/api/v1/accounts/{account_no}/transactions"
        # 远程调用，使用并行方式实现
        account_info, txns_info = await asyncio.gather(
            httpx_client.http_client.get(account_url),
            httpx_client.http_client.get(txns_url, params={"page_size": 5}),
        )

        account_payload = account_info.json()
        txns_payload = txns_info.json()
        chunk = json.dumps(
            {
                "account_detail": account_payload.get("data") or {"message": account_payload.get("message")},
                "recent_transactions": txns_payload.get("data") or {"message": txns_payload.get("message")},
            },
            ensure_ascii=False,
        )
        return [KnowledgeChunk(content=chunk)]


# faq
## 查询固定问题和固定答案
class FAQProvider(KnowledgeProvider):
    provider_id = "faq.default"

    async def execute(self, state: DialogueState,
                      user_message: UserMessage) -> list[KnowledgeChunk]:
        # TODO
        return [KnowledgeChunk(content="未检索到相关问题")]


# rag
## 调用知识库里面查询接口得到结果
class RAGProvider(KnowledgeProvider):
    provider_id = "rag.default"

    async def execute(self, state: DialogueState,
                      user_message: UserMessage) -> list[KnowledgeChunk]:
        # RAG知识库查询知识接口（TODO）
        return [KnowledgeChunk(content="未检索到相关信息")]
