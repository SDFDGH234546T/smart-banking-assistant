"""Centralized constants and enum whitelists for `chat_app`.

Account status and support ticket type values were verified read-only against
the MySQL `bank_account`, `support_ticket`, and `dim_channel` tables as well as
`app/routers/accounts.py` and `app/routers/operations.py`.
"""

from __future__ import annotations

# --- 渠道与会话生命周期常量 ---
# 对接中台时固定透传的手机银行渠道编码（已核查 dim_channel 表确实存在该记录）
DEFAULT_CHANNEL_CODE = "MOBILE_BANK"

# 会话状态：超过 TTL（默认 1 小时）后旧会话置为 expired 并新建 active 会话
SESSION_STATUS_ACTIVE = "active"
SESSION_STATUS_EXPIRED = "expired"
# /api/chat/history 返回非空历史时末尾追加的分割线文本，需与前端 App.vue 保持一致
HISTORY_DIVIDER_TEXT = "以上为历史消息"

# --- 银行账户状态枚举 ---
# bank_account.account_status 为 varchar(64)，存量数据有 normal/closed，中台代码含 active
ACCOUNT_STATUS_NORMAL = "normal"
ACCOUNT_STATUS_ACTIVE = "active"
ACCOUNT_STATUS_FROZEN = "frozen"
ACCOUNT_STATUS_LOST = "lost"
ACCOUNT_STATUS_CLOSED = "closed"

# 账户全量合法状态集合（用于展示与状态判断）
ACCOUNT_STATUSES: frozenset[str] = frozenset(
    {
        ACCOUNT_STATUS_NORMAL,
        ACCOUNT_STATUS_ACTIVE,
        ACCOUNT_STATUS_FROZEN,
        ACCOUNT_STATUS_LOST,
        ACCOUNT_STATUS_CLOSED,
    }
)
# S3 账户状态变更写接口的严格白名单，仅允许冻结（frozen）或挂失（lost），防止误关户
TARGET_ACCOUNT_STATUSES: frozenset[str] = frozenset(
    {
        ACCOUNT_STATUS_FROZEN,
        ACCOUNT_STATUS_LOST,
    }
)

# --- 客服工单类型枚举 ---
# support_ticket.ticket_type 为 varchar(64)，存量含 transaction_issue/repayment_issue
TICKET_TYPE_GENERAL = "general_inquiry"
TICKET_TYPE_ACCOUNT = "account_issue"
TICKET_TYPE_TRANSACTION = "transaction_issue"
TICKET_TYPE_REPAYMENT = "repayment_issue"

TICKET_TYPES: frozenset[str] = frozenset(
    {
        TICKET_TYPE_GENERAL,
        TICKET_TYPE_ACCOUNT,
        TICKET_TYPE_TRANSACTION,
        TICKET_TYPE_REPAYMENT,
    }
)
# S5 转人工建单默认值：无具体关联业务对象时 related_type 传 "none"
DEFAULT_TICKET_TYPE = TICKET_TYPE_GENERAL
DEFAULT_TICKET_RELATED_TYPE = "none"

# --- 确定性确认 / 取消关键词集合 ---
# 由代码层优先拦截，不依赖 LLM 语义猜测，确保敏感写操作（冻结/挂失）确认与取消绝对可靠
CONFIRM_KEYWORDS: frozenset[str] = frozenset(
    {"确认", "确定", "是的", "同意", "办理", "好的"}
)
CANCEL_KEYWORDS: frozenset[str] = frozenset(
    {"取消", "不用了", "算了", "放弃", "不办了"}
)

# --- NLU 意图分类与任务白名单 ---
# 三大顶层意图：闲聊、规则问答（不中断当前任务）、多步骤任务流
INTENT_CATEGORY_CHITCHAT = "chitchat"
INTENT_CATEGORY_KNOWLEDGE_QUERY = "knowledge_query"
INTENT_CATEGORY_TASK_FLOW = "task_flow"

INTENT_CATEGORIES: frozenset[str] = frozenset(
    {
        INTENT_CATEGORY_CHITCHAT,
        INTENT_CATEGORY_KNOWLEDGE_QUERY,
        INTENT_CATEGORY_TASK_FLOW,
    }
)

# MVP 支持的 5 大核心业务任务标识，用于防幻觉白名单校验
TASK_TYPE_QUERY_BALANCE = "query_balance"
TASK_TYPE_QUERY_TRANSACTIONS = "query_transactions"
TASK_TYPE_QUERY_TRANSACTION_DETAIL = "query_transaction_detail"
TASK_TYPE_FREEZE_OR_LOSS = "freeze_or_loss_account"
TASK_TYPE_TRANSFER_HUMAN = "transfer_human"

TASK_TYPES: frozenset[str] = frozenset(
    {
        TASK_TYPE_QUERY_BALANCE,
        TASK_TYPE_QUERY_TRANSACTIONS,
        TASK_TYPE_QUERY_TRANSACTION_DETAIL,
        TASK_TYPE_FREEZE_OR_LOSS,
        TASK_TYPE_TRANSFER_HUMAN,
    }
)
# 敏感写操作集合：槽位齐全后必须进入 awaiting_confirm 等待用户二次确认
SENSITIVE_WRITE_TASK_TYPES: frozenset[str] = frozenset({TASK_TYPE_FREEZE_OR_LOSS})

# 双区任务中 active_task 的流转阶段：收集槽位中 / 等待二次确认
TASK_STAGE_COLLECTING_SLOTS = "collecting_slots"
TASK_STAGE_AWAITING_CONFIRM = "awaiting_confirm"

# S4 银行业务规则问答主题白名单，对应中台 foundation 五大配置查询接口
FAQ_TOPICS: frozenset[str] = frozenset(
    {
        "transfer_limit",
        "fee_standard",
        "account_product",
        "branch",
        "channel",
        "currency",
        "general",
    }
)

# S2 交易明细查询允许过滤的交易类型白名单
TRANSACTION_TYPES: frozenset[str] = frozenset(
    {
        "deposit",
        "withdraw",
        "transfer",
        "consumption",
        "refund",
    }
)

# 低于该置信度阈值时判定为意图模糊（ambiguous），触发澄清回复
NLU_CONFIDENCE_THRESHOLD = 0.6
