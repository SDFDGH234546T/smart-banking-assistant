"""Unit tests for `chat_app.llm.parser`."""

from __future__ import annotations

import json

from chat_app.llm import parse_nlu_response


def test_parse_nlu_strips_markdown_fence_and_succeeds() -> None:
    raw = """```json
{
  "intents": [
    {
      "category": "task_flow",
      "task_type": "freeze_or_loss_account",
      "faq_topic": null,
      "confidence": 0.95
    }
  ],
  "slots": {
    "account_no": "ACC0000000001",
    "target_status": "frozen",
    "reason": "卡丢了"
  },
  "ambiguity_reason": null
}
```"""
    outcome = parse_nlu_response(raw)
    assert outcome.ok is True
    assert outcome.result is not None
    assert outcome.result.intents[0].task_type == "freeze_or_loss_account"
    assert outcome.result.slots.target_status == "frozen"


def test_parse_nlu_normalizes_unknown_faq_topic_to_general() -> None:
    raw = json.dumps(
        {
            "intents": [
                {
                    "category": "knowledge_query",
                    "task_type": None,
                    "faq_topic": "unknown_topic",
                    "confidence": 0.88,
                }
            ],
            "slots": {},
        }
    )
    outcome = parse_nlu_response(raw)
    assert outcome.ok is True
    assert outcome.result is not None
    assert outcome.result.intents[0].faq_topic == "general"


def test_parse_nlu_rejects_multi_intent_conflict() -> None:
    raw = json.dumps(
        {
            "intents": [
                {"category": "task_flow", "task_type": "query_balance", "confidence": 0.9},
                {
                    "category": "task_flow",
                    "task_type": "freeze_or_loss_account",
                    "confidence": 0.85,
                },
            ],
            "slots": {},
        }
    )
    outcome = parse_nlu_response(raw)
    assert outcome.ok is False
    assert outcome.failure_type == "multi_intent_conflict"
    assert outcome.clarification_reply is not None
    assert "同时提到了多项业务" in outcome.clarification_reply


def test_parse_nlu_detects_ambiguous_zero_intent_and_low_confidence() -> None:
    empty_raw = json.dumps({"intents": [], "slots": {}})
    outcome_empty = parse_nlu_response(empty_raw)
    assert outcome_empty.ok is False
    assert outcome_empty.failure_type == "ambiguous"

    low_conf_raw = json.dumps(
        {
            "intents": [{"category": "chitchat", "confidence": 0.4}],
            "slots": {},
        }
    )
    outcome_low = parse_nlu_response(low_conf_raw)
    assert outcome_low.ok is False
    assert outcome_low.failure_type == "ambiguous"


def test_parse_nlu_detects_out_of_scope_and_invalid_schema() -> None:
    oos_raw = json.dumps(
        {
            "intents": [
                {
                    "category": "task_flow",
                    "task_type": "apply_loan",
                    "confidence": 0.91,
                }
            ],
            "slots": {},
        }
    )
    outcome_oos = parse_nlu_response(oos_raw)
    assert outcome_oos.ok is False
    assert outcome_oos.failure_type == "out_of_scope"
    assert outcome_oos.clarification_reply is not None
    assert "暂不支持" in outcome_oos.clarification_reply

    outcome_bad = parse_nlu_response("not a json at all")
    assert outcome_bad.ok is False
    assert outcome_bad.failure_type == "invalid_schema"
