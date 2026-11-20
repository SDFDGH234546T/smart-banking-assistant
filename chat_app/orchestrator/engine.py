"""Main chat orchestrator coordinating session lifecycle, NLU, and handlers."""

from __future__ import annotations

import logging
from typing import Any

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from chat_app.clients.bank_client import BankClient, BankClientError
from chat_app.config import Settings, get_settings
from chat_app.constants import (
    CANCEL_KEYWORDS,
    CANCEL_SUBSTRINGS,
    CONFIRM_KEYWORDS,
    INTENT_CATEGORY_CHITCHAT,
    INTENT_CATEGORY_KNOWLEDGE_QUERY,
    TASK_STAGE_AWAITING_CONFIRM,
    TASK_TYPE_FREEZE_OR_LOSS,
    TASK_TYPE_QUERY_BALANCE,
    TASK_TYPE_QUERY_TRANSACTION_DETAIL,
    TASK_TYPE_QUERY_TRANSACTIONS,
    TASK_TYPE_TRANSFER_HUMAN,
)
from chat_app.db.models import ChatMessage
from chat_app.db.repository import (
    get_or_create_active_session,
    get_recent_messages,
    save_turn,
)
from chat_app.llm.client import LLMClient, LLMClientError
from chat_app.llm.parser import NLUParseOutcome, parse_nlu_response
from chat_app.llm.prompts import build_nlu_messages
from chat_app.orchestrator.handlers.account import handle_account_query
from chat_app.orchestrator.handlers.chitchat import handle_chitchat
from chat_app.orchestrator.handlers.faq import handle_faq_query
from chat_app.orchestrator.handlers.handoff import handle_transfer_human
from chat_app.orchestrator.handlers.object_card import handle_object_card
from chat_app.orchestrator.handlers.status_change import (
    execute_status_change,
    handle_status_change_step,
)
from chat_app.orchestrator.handlers.transaction import handle_transaction_query
from chat_app.orchestrator.slot_templates import build_slot_prompt, get_task_label
from chat_app.orchestrator.task_manager import TaskManager, extract_non_empty_slots
from chat_app.schemas.chat import BotMessage, ChatRequest, ChatResponse, ObjectPayload
from chat_app.schemas.nlu import TaskItem, TaskState

logger = logging.getLogger(__name__)


def _serialize_history_for_nlu(messages: list[ChatMessage]) -> list[dict[str, str]]:
    """将数据库历史消息转为 NLU/摘要可用的轻量文本列表，包含对象卡片摘要。"""
    serialized: list[dict[str, str]] = []
    for msg in messages:
        if msg.content_type == "object" and msg.object_payload_json:
            obj = msg.object_payload_json
            text = f"[发送对象卡片: type={obj.get('type')}, id={obj.get('id')}]"
        else:
            text = (msg.text_content or "").strip()
        if text:
            serialized.append({"role": msg.role, "text": text})
    return serialized


def _parse_cached_object(raw_obj: dict[str, Any] | None) -> ObjectPayload | None:
    """安全反序列化会话缓存的焦点对象卡片，异常时忽略缓存防止主流程中断。"""
    if not raw_obj:
        return None
    try:
        return ObjectPayload.model_validate(raw_obj)
    except ValidationError:
        return None


def _is_cancel_intent(text: str) -> bool:
    """判断用户输入是否为确定性取消意图（兼容标点与常见口语短句变体）。"""
    normalized = text.strip().rstrip("。.！!？?~～，, ")
    if not normalized:
        return False
    if normalized in CANCEL_KEYWORDS:
        return True
    # 短句且非疑问句时匹配取消短语，避免长句或疑问句（如“为什么不能取消”）被误拦截
    if len(normalized) <= 12 and not any(q in normalized for q in ("为什么", "怎么", "如何", "能否", "可以吗")):
        return any(sub in normalized for sub in CANCEL_SUBSTRINGS)
    return False


class ChatOrchestrator:
    """智能银行客服对话主编排器。"""

    def __init__(
        self,
        *,
        bank_client: BankClient,
        llm_client: LLMClient,
        settings: Settings | None = None,
    ) -> None:
        self._bank_client = bank_client
        self._llm_client = llm_client
        self._settings = settings or get_settings()

    async def _classify_intent_with_retry(
        self,
        user_text: str,
        *,
        history_messages: list[dict[str, str]],
        active_task: TaskItem | None,
        cached_object: ObjectPayload | None,
    ) -> NLUParseOutcome:
        """调用 LLM 进行意图识别与防幻觉校验；仅在 invalid_schema 时触发 1 次重试。"""
        nlu_messages = build_nlu_messages(
            user_text,
            history_messages=history_messages,
            active_task=active_task,
            cached_object=cached_object,
        )
        raw_output = await self._llm_client.ainvoke(nlu_messages)
        outcome = parse_nlu_response(raw_output)
        if not outcome.ok and outcome.failure_type == "invalid_schema":
            raw_retry = await self._llm_client.ainvoke(nlu_messages)
            outcome = parse_nlu_response(raw_retry)
        return outcome

    async def _execute_ready_task(
        self,
        sender_id: str,
        *,
        task: TaskItem,
        task_state: TaskState,
        history_messages: list[dict[str, str]],
        user_text: str,
    ) -> str:
        """分发执行槽位已齐全的非写操作业务任务。"""
        if task.task_type == TASK_TYPE_QUERY_BALANCE:
            return await handle_account_query(
                sender_id,
                bank_client=self._bank_client,
                task_state=task_state,
                slots=task.slots,
            )
        if task.task_type in (
            TASK_TYPE_QUERY_TRANSACTIONS,
            TASK_TYPE_QUERY_TRANSACTION_DETAIL,
        ):
            return await handle_transaction_query(
                sender_id,
                task_type=task.task_type,
                bank_client=self._bank_client,
                task_state=task_state,
                slots=task.slots,
            )
        if task.task_type == TASK_TYPE_TRANSFER_HUMAN:
            return await handle_transfer_human(
                sender_id,
                user_text=user_text,
                bank_client=self._bank_client,
                task_state=task_state,
                slots=task.slots,
                history_messages=history_messages,
            )
        # 理论不可达（TASK_TYPES 白名单已拦截），防御性兜底
        return "暂不支持该业务办理，请回复“转人工”由客服专员为您处理。"

    async def _process_text_turn(
        self,
        sender_id: str,
        cleaned_text: str,
        *,
        task_state: TaskState,
        cached_object_dict: dict[str, Any] | None,
        history_messages: list[dict[str, str]],
    ) -> tuple[str, str, str | None]:
        """处理纯文本消息分支：确定性取消/确认拦截 → NLU → 路由执行。"""
        # 1. 代码层确定性取消拦截，不依赖 LLM 语义猜测
        if task_state.active_task is not None and _is_cancel_intent(cleaned_text):
            cancelled_label = get_task_label(task_state.active_task.task_type)
            resumed = TaskManager.finish_active_task(task_state)
            hint = TaskManager.build_resume_hint(resumed)
            reply = f"已为您取消【{cancelled_label}】办理。"
            if hint:
                reply = f"{reply}\n\n{hint}"
            return reply, "task_flow", "task_cancelled"

        # 2. 代码层确定性二次确认拦截，确保冻结/挂失写操作安全落地
        if (
            task_state.active_task is not None
            and task_state.active_task.stage == TASK_STAGE_AWAITING_CONFIRM
            and cleaned_text in CONFIRM_KEYWORDS
        ):
            confirmed_task_type = task_state.active_task.task_type
            reply = await execute_status_change(
                sender_id,
                bank_client=self._bank_client,
                task_state=task_state,
                task=task_state.active_task,
            )
            return reply, "task_flow", confirmed_task_type

        # 3. 常规文本或填槽中：调用 NLU + 防幻觉风控校验
        cached_obj_model = _parse_cached_object(cached_object_dict)
        nlu_outcome = await self._classify_intent_with_retry(
            cleaned_text,
            history_messages=history_messages,
            active_task=task_state.active_task,
            cached_object=cached_obj_model,
        )
        if not nlu_outcome.ok or nlu_outcome.result is None:
            return (
                nlu_outcome.clarification_reply
                or "抱歉，我没太明白您的意思，请换一种说法再试一次。",
                "validation_failed",
                nlu_outcome.failure_type,
            )

        intent = nlu_outcome.result.intents[0]
        nlu_slots = nlu_outcome.result.slots

        # 4. 三大顶层意图路由
        if intent.category == INTENT_CATEGORY_CHITCHAT:
            reply = await handle_chitchat(
                user_text=cleaned_text,
                task_state=task_state,
                llm_client=self._llm_client,
            )
            return reply, INTENT_CATEGORY_CHITCHAT, INTENT_CATEGORY_CHITCHAT

        if intent.category == INTENT_CATEGORY_KNOWLEDGE_QUERY:
            faq_topic = intent.faq_topic or "general"
            reply = await handle_faq_query(
                sender_id,
                user_text=cleaned_text,
                faq_topic=faq_topic,
                slots=extract_non_empty_slots(nlu_slots),
                bank_client=self._bank_client,
                llm_client=self._llm_client,
            )
            return reply, INTENT_CATEGORY_KNOWLEDGE_QUERY, faq_topic

        # 5. task_flow 双区调度与槽位填充
        assert intent.task_type is not None
        task = TaskManager.start_or_update_task(
            task_state,
            intent.task_type,
            new_slots=nlu_slots,
            cached_object=cached_object_dict,
        )

        if task.task_type == TASK_TYPE_FREEZE_OR_LOSS:
            reply = await handle_status_change_step(
                sender_id,
                bank_client=self._bank_client,
                task_state=task_state,
                task=task,
            )
            return reply, "task_flow", task.task_type

        if task.missing_slots:
            return (
                build_slot_prompt(task.task_type, task.missing_slots),
                "task_flow",
                task.task_type,
            )

        reply = await self._execute_ready_task(
            sender_id,
            task=task,
            task_state=task_state,
            history_messages=history_messages,
            user_text=cleaned_text,
        )
        return reply, "task_flow", task.task_type

    async def handle_chat(
        self,
        db: AsyncSession,
        request: ChatRequest,
    ) -> ChatResponse:
        """执行单轮对话完整编排并事务性落库，返回同步 JSON 响应。"""
        session, _ = await get_or_create_active_session(
            db,
            request.sender_id,
            ttl_seconds=self._settings.CHAT_SESSION_TTL_SECONDS,
        )
        task_state = TaskManager.load_state(session.task_state_json)
        cached_object_dict = session.cached_object_json
        update_cached_object = False

        recent_rows = await get_recent_messages(
            db,
            session.session_id,
            limit=self._settings.CHAT_HISTORY_WINDOW,
        )
        history_messages = _serialize_history_for_nlu(recent_rows)

        user_content_type = "object" if request.object is not None else "text"
        user_object_payload = (
            request.object.model_dump() if request.object is not None else None
        )
        intent_category: str | None = None
        intent_detail: str | None = None

        try:
            if request.object is not None:
                card_outcome = handle_object_card(
                    request.object,
                    task_state,
                    cached_object_dict,
                )
                if card_outcome.cached_object != cached_object_dict:
                    cached_object_dict = card_outcome.cached_object
                    update_cached_object = True

                intent_category = "object_input"
                intent_detail = card_outcome.intent_detail

                if card_outcome.ready_to_execute_task is not None:
                    reply_text = await self._execute_ready_task(
                        request.sender_id,
                        task=card_outcome.ready_to_execute_task,
                        task_state=task_state,
                        history_messages=history_messages,
                        user_text=request.text or "",
                    )
                else:
                    reply_text = (
                        card_outcome.reply_text
                        or "已收到您的卡片信息，请告诉我您需要办理的业务。"
                    )
            else:
                assert request.text is not None
                reply_text, intent_category, intent_detail = await self._process_text_turn(
                    request.sender_id,
                    request.text,
                    task_state=task_state,
                    cached_object_dict=cached_object_dict,
                    history_messages=history_messages,
                )
        except (BankClientError, LLMClientError) as exc:
            logger.warning(
                "Downstream service error during chat turn (sender_id=%s): %s",
                request.sender_id,
                exc.message,
            )
            reply_text = exc.message
            intent_category = intent_category or "downstream_error"

        await save_turn(
            db,
            session,
            user_content_type=user_content_type,
            user_text=request.text,
            user_object_payload=user_object_payload,
            bot_text=reply_text,
            intent_category=intent_category,
            intent_detail=intent_detail,
            task_state_json=TaskManager.dump_state(task_state),
            cached_object_json=cached_object_dict,
            update_cached_object=update_cached_object,
        )
        return ChatResponse(messages=[BotMessage(text=reply_text)])
