"""Unit tests for `chat_app.schemas.chat`."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from chat_app.constants import HISTORY_DIVIDER_TEXT
from chat_app.schemas import (
    BotMessage,
    ChatRequest,
    ChatResponse,
    HistoryMessage,
    HistoryResponse,
    ObjectPayload,
)


def test_object_payload_accepts_account_and_transaction() -> None:
    account_obj = ObjectPayload(
        type="account",
        id=" ACC0000000001 ",
        title="活期储蓄账户",
        attributes={"balance_amount": "12500.00", "currency_code": "CNY"},
    )
    assert account_obj.type == "account"
    assert account_obj.id == "ACC0000000001"
    assert account_obj.attributes["currency_code"] == "CNY"

    txn_obj = ObjectPayload(type="transaction", id="TXN0000000001")
    assert txn_obj.type == "transaction"
    assert txn_obj.title is None
    assert txn_obj.attributes == {}


def test_object_payload_rejects_invalid_type_or_blank_id() -> None:
    with pytest.raises(ValidationError):
        ObjectPayload(type="loan", id="L001")  # type: ignore[arg-type]

    with pytest.raises(ValidationError):
        ObjectPayload(type="account", id="   ")


def test_chat_request_validates_text_or_object() -> None:
    req_text = ChatRequest(sender_id=" CUS00000001 ", text=" 查询账户余额 ")
    assert req_text.sender_id == "CUS00000001"
    assert req_text.text == "查询账户余额"
    assert req_text.object is None

    req_obj = ChatRequest(
        sender_id="CUS00000001",
        object=ObjectPayload(type="account", id="ACC0000000001"),
    )
    assert req_obj.text is None
    assert req_obj.object is not None

    with pytest.raises(ValidationError):
        ChatRequest(sender_id="CUS00000001", text="   ", object=None)

    with pytest.raises(ValidationError):
        ChatRequest(sender_id="   ", text="你好")


def test_bot_message_and_chat_response() -> None:
    msg = BotMessage(text=" 您好，请问有什么可以帮您？ ")
    resp = ChatResponse(messages=[msg])
    dumped = resp.model_dump(exclude_none=True)
    assert dumped == {"messages": [{"text": "您好，请问有什么可以帮您？"}]}

    with pytest.raises(ValidationError):
        BotMessage(text="   ", object=None)


def test_history_message_and_divider_behavior() -> None:
    user_msg = HistoryMessage(role="user", text="查询余额")
    bot_obj = HistoryMessage(
        role="bot",
        object=ObjectPayload(type="account", id="ACC0000000001", title="活期账户"),
    )
    divider = HistoryMessage(role="divider")
    assert divider.text == HISTORY_DIVIDER_TEXT

    history = HistoryResponse(messages=[user_msg, bot_obj, divider])
    assert len(history.messages) == 3
    assert history.messages[-1].role == "divider"

    empty_history = HistoryResponse()
    assert empty_history.model_dump() == {"messages": []}

    with pytest.raises(ValidationError):
        HistoryMessage(
            role="divider",
            object=ObjectPayload(type="account", id="ACC0000000001"),
        )

    with pytest.raises(ValidationError):
        HistoryMessage(role="user", text=None, object=None)
