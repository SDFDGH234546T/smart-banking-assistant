"""Unit tests for pure-code slot specs and deterministic prompt templates."""

from __future__ import annotations

import pytest

from chat_app.constants import (
    ACCOUNT_STATUS_FROZEN,
    ACCOUNT_STATUS_LOST,
    TASK_TYPE_FREEZE_OR_LOSS,
    TASK_TYPE_QUERY_BALANCE,
    TASK_TYPE_QUERY_TRANSACTION_DETAIL,
    TASK_TYPE_QUERY_TRANSACTIONS,
    TASK_TYPE_TRANSFER_HUMAN,
)
from chat_app.orchestrator.slot_templates import (
    OBJECT_TYPE_TO_SLOT,
    REQUIRED_SLOTS,
    build_confirm_prompt,
    build_slot_prompt,
    compute_missing_slots,
    get_task_label,
)


def test_required_slots_and_object_mapping() -> None:
    """验证各任务必填槽位规格及卡片类型映射是否对齐 SPEC 约定。"""
    assert REQUIRED_SLOTS[TASK_TYPE_QUERY_BALANCE] == ()
    assert REQUIRED_SLOTS[TASK_TYPE_QUERY_TRANSACTIONS] == ("account_no",)
    assert REQUIRED_SLOTS[TASK_TYPE_QUERY_TRANSACTION_DETAIL] == ("transaction_no",)
    assert REQUIRED_SLOTS[TASK_TYPE_FREEZE_OR_LOSS] == (
        "account_no",
        "target_status",
        "reason",
    )
    assert REQUIRED_SLOTS[TASK_TYPE_TRANSFER_HUMAN] == ()

    assert OBJECT_TYPE_TO_SLOT == {
        "account": "account_no",
        "transaction": "transaction_no",
    }


def test_compute_missing_slots_treats_blank_as_missing() -> None:
    """空白字符串与 None 均应视为缺失，保持必填顺序返回。"""
    missing = compute_missing_slots(
        TASK_TYPE_FREEZE_OR_LOSS,
        {"account_no": "  ", "target_status": ACCOUNT_STATUS_FROZEN, "reason": None},
    )
    assert missing == ["account_no", "reason"]

    complete = compute_missing_slots(
        TASK_TYPE_FREEZE_OR_LOSS,
        {
            "account_no": "ACC0000000001",
            "target_status": ACCOUNT_STATUS_LOST,
            "reason": "银行卡遗失",
        },
    )
    assert complete == []


def test_compute_missing_slots_rejects_unknown_task_type() -> None:
    """非法任务类型应抛出 ValueError，防止绕过白名单。"""
    with pytest.raises(ValueError, match="非法任务类型"):
        compute_missing_slots("transfer_money", {})


def test_build_slot_prompt_single_and_multiple_missing() -> None:
    """验证单槽位精准追问与多槽位合并追问文案。"""
    tx_prompt = build_slot_prompt(TASK_TYPE_QUERY_TRANSACTIONS, ["account_no"])
    assert "账户号" in tx_prompt
    assert "账户卡片" in tx_prompt

    status_prompt = build_slot_prompt(TASK_TYPE_FREEZE_OR_LOSS, ["target_status"])
    assert "冻结" in status_prompt
    assert "挂失" in status_prompt

    multi_prompt = build_slot_prompt(
        TASK_TYPE_FREEZE_OR_LOSS,
        ["account_no", "target_status", "reason"],
    )
    assert "银行账户号" in multi_prompt
    assert "办理类型" in multi_prompt
    assert "申请原因" in multi_prompt
    assert "账户卡片" in multi_prompt


def test_build_confirm_prompt_for_freeze_and_loss() -> None:
    """验证冻结/挂失二次确认摘要包含完整要素及确认/取消指令。"""
    prompt = build_confirm_prompt(
        TASK_TYPE_FREEZE_OR_LOSS,
        {
            "account_no": "ACC0000000001",
            "target_status": ACCOUNT_STATUS_LOST,
            "reason": "卡片不慎丢失",
        },
    )
    assert "账户挂失" in prompt
    assert "ACC0000000001" in prompt
    assert "卡片不慎丢失" in prompt
    assert "确认" in prompt
    assert "取消" in prompt
    assert get_task_label(TASK_TYPE_FREEZE_OR_LOSS) == "账户冻结/挂失"
