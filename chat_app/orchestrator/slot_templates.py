"""Pure-code slot specifications and deterministic Chinese prompt templates."""

from __future__ import annotations

from typing import Any

from chat_app.constants import (
    ACCOUNT_STATUS_FROZEN,
    ACCOUNT_STATUS_LOST,
    TASK_TYPE_FREEZE_OR_LOSS,
    TASK_TYPE_QUERY_BALANCE,
    TASK_TYPE_QUERY_TRANSACTION_DETAIL,
    TASK_TYPE_QUERY_TRANSACTIONS,
    TASK_TYPE_TRANSFER_HUMAN,
    TASK_TYPES,
)

# 各业务任务的必填槽位顺序表：按声明顺序逐项校验与追问，保证多轮交互体验确定可控
REQUIRED_SLOTS: dict[str, tuple[str, ...]] = {
    TASK_TYPE_QUERY_BALANCE: (),
    TASK_TYPE_QUERY_TRANSACTIONS: ("account_no",),
    TASK_TYPE_QUERY_TRANSACTION_DETAIL: ("transaction_no",),
    TASK_TYPE_FREEZE_OR_LOSS: ("account_no", "target_status", "reason"),
    TASK_TYPE_TRANSFER_HUMAN: (),
}

# 前端对象卡片类型到任务槽位名的确定性映射，供对象分支与缓存自动填槽复用
OBJECT_TYPE_TO_SLOT: dict[str, str] = {
    "account": "account_no",
    "transaction": "transaction_no",
}

# 任务中文名称映射，用于追问、二次确认及暂缓任务恢复提示
TASK_TYPE_LABELS: dict[str, str] = {
    TASK_TYPE_QUERY_BALANCE: "账户与余额查询",
    TASK_TYPE_QUERY_TRANSACTIONS: "交易明细查询",
    TASK_TYPE_QUERY_TRANSACTION_DETAIL: "单笔交易查询",
    TASK_TYPE_FREEZE_OR_LOSS: "账户冻结/挂失",
    TASK_TYPE_TRANSFER_HUMAN: "转人工客服",
}

# 槽位中文名称映射，用于缺失提示与不匹配澄清
SLOT_LABELS: dict[str, str] = {
    "account_no": "银行账户号",
    "transaction_no": "交易流水号",
    "target_status": "办理类型（冻结或挂失）",
    "reason": "申请原因",
}

# 敏感写操作目标状态中文标签，避免直接向用户暴露英文枚举值
TARGET_STATUS_LABELS: dict[str, str] = {
    ACCOUNT_STATUS_FROZEN: "冻结",
    ACCOUNT_STATUS_LOST: "挂失",
}

# 单槽位纯代码固定追问模板（按 (task_type, slot_name) 或通用 slot_name 索引，零 LLM 调用）
_TASK_SLOT_PROMPTS: dict[tuple[str, str], str] = {
    (
        TASK_TYPE_QUERY_TRANSACTIONS,
        "account_no",
    ): "请提供您要查询交易明细的银行账户号（也可以直接从右侧栏发送对应的账户卡片）。",
    (
        TASK_TYPE_QUERY_TRANSACTION_DETAIL,
        "transaction_no",
    ): "请提供您要查询的交易流水号（也可以直接从右侧栏发送对应的交易卡片）。",
    (
        TASK_TYPE_FREEZE_OR_LOSS,
        "account_no",
    ): "请提供需要办理冻结或挂失的银行账户号（也可以直接从右侧栏发送对应的账户卡片）。",
    (
        TASK_TYPE_FREEZE_OR_LOSS,
        "target_status",
    ): "请明确您需要办理的操作类型：账户【冻结】还是【挂失】？",
    (
        TASK_TYPE_FREEZE_OR_LOSS,
        "reason",
    ): "请简述申请冻结或挂失的原因（例如：银行卡遗失、怀疑账户存在异常交易等）。",
}


def get_task_label(task_type: str) -> str:
    """获取业务任务的中文显示名称。"""
    return TASK_TYPE_LABELS.get(task_type, task_type)


def _is_slot_filled(value: Any) -> bool:
    """判断槽位值是否有效（排除 None 与纯空白字符串）。"""
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    return True


def compute_missing_slots(task_type: str, slots: dict[str, Any]) -> list[str]:
    """按任务白名单规格计算当前仍缺失的必填槽位列表。"""
    if task_type not in TASK_TYPES:
        raise ValueError(f"非法任务类型: {task_type}")
    required = REQUIRED_SLOTS[task_type]
    return [slot_name for slot_name in required if not _is_slot_filled(slots.get(slot_name))]


def build_slot_prompt(task_type: str, missing_slots: list[str]) -> str:
    """根据任务类型与缺失槽位生成确定性中文追问文案（零 LLM 调用）。"""
    if task_type not in TASK_TYPES:
        raise ValueError(f"非法任务类型: {task_type}")

    task_label = get_task_label(task_type)
    if not missing_slots:
        return f"当前【{task_label}】所需信息已齐全。"

    # 仅缺 1 个槽位时返回最精准的引导文案，降低用户阅读负担
    if len(missing_slots) == 1:
        slot_name = missing_slots[0]
        specific_prompt = _TASK_SLOT_PROMPTS.get((task_type, slot_name))
        if specific_prompt:
            return specific_prompt
        slot_label = SLOT_LABELS.get(slot_name, slot_name)
        return f"办理【{task_label}】还需要您提供{slot_label}。"

    # 缺失多个槽位时合并列出清单，允许用户一次性补充完整
    missing_labels = [SLOT_LABELS.get(name, name) for name in missing_slots]
    joined = "、".join(missing_labels)
    if "account_no" in missing_slots:
        return f"正在为您办理【{task_label}】，请补充以下信息：{joined}（账户号也可直接从右侧栏发送账户卡片）。"
    return f"正在为您办理【{task_label}】，请补充以下信息：{joined}。"


def build_confirm_prompt(task_type: str, slots: dict[str, Any]) -> str:
    """为敏感写操作生成包含完整核对要素的二次确认摘要文案。"""
    if task_type != TASK_TYPE_FREEZE_OR_LOSS:
        task_label = get_task_label(task_type)
        return f"请确认是否继续办理【{task_label}】？回复“确认”继续，回复“取消”放弃。"

    account_no = str(slots.get("account_no", "")).strip()
    target_status = str(slots.get("target_status", "")).strip()
    reason = str(slots.get("reason", "")).strip()
    action_label = TARGET_STATUS_LABELS.get(target_status, target_status)

    return (
        "请核对以下账户状态变更信息：\n"
        f"- 办理类型：账户{action_label}\n"
        f"- 目标账户：{account_no}\n"
        f"- 申请原因：{reason}\n"
        "请回复“确认”执行办理，或回复“取消”放弃本次操作。"
    )
