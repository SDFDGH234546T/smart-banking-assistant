"""
这个模块作用定义知识检索范围
"""
from dataclasses import dataclass, field


# 定义知识检索，范围，不同范围对应答案位置
# 1 封装知识检索数据
@dataclass
class KnowledgeIntent:
    id: str  # 意图识别值    account_info
    description: str  # llm更好理解id含义  "账户信息咨询"
    # 问题答案位置 provider类里面属性值对应
    provider_ids: list[str] = field(default_factory=list)
    # 规则：查询账户、交易信息都需要从聚焦对象获取值
    requires_object: str | None = None


# 2 创建字典
KNOWLEDGE_INTENTS: dict[str, KnowledgeIntent] = {
    "account_info": KnowledgeIntent(
        id="account_info",
        description="银行账户信息咨询（包括账户状态、余额、冻结金额、所属产品及近期交易）",
        provider_ids=["api.account"],
        requires_object="account",
    ),
    "transaction_info": KnowledgeIntent(
        id="transaction_info",
        description="单笔交易流水详情咨询（包括交易状态、金额、渠道流水及对账状态）",
        provider_ids=["api.transaction"],
        requires_object="transaction",
    ),
    "transfer_limit_policy": KnowledgeIntent(
        id="transfer_limit_policy",
        description="转账限额与手续费率政策咨询",
        provider_ids=["faq.default", "rag.default"],
    ),
    "freeze_unfreeze_policy": KnowledgeIntent(
        id="freeze_unfreeze_policy",
        description="账户冻结、挂失与解冻解挂政策咨询",
        provider_ids=["faq.default", "rag.default"],
    ),
    "account_opening_policy": KnowledgeIntent(
        id="account_opening_policy",
        description="开户条件、账户分类与绑卡规则咨询",
        provider_ids=["faq.default", "rag.default"],
    ),
    "risk_control_policy": KnowledgeIntent(
        id="risk_control_policy",
        description="账户风控规则与异常交易反欺诈说明咨询",
        provider_ids=["rag.default"],
    ),
    "general_banking_info": KnowledgeIntent(
        id="general_banking_info",
        description="银行通用业务与服务信息咨询",
        provider_ids=["faq.default", "rag.default"],
    ),
}
