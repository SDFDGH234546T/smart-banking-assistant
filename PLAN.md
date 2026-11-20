# 智能银行客服后端（`chat_app`）实施计划（PLAN）

> 本计划严格基于 [SPEC.md](file:///d:/0708/尚硅谷大模型项目实战之掌柜小二实战/finance-data/SPEC.md) 拆解，共 **7 个阶段、24 个细粒度子任务**。
> 执行规范遵循 [AGENTS.md](file:///d:/0708/尚硅谷大模型项目实战之掌柜小二实战/finance-data/AGENTS.md)：每次仅执行你指派的单个子任务，完成“编码 → 验证 → 修复”闭环后勾选并停止复盘；单元测试统一采用 Mock（不依赖真实 LLM 与中台 8000 服务），阶段 7 统一做三端真实联调验收。
> **全链路异步约定**：后端内部严格采用 `async/await` 非阻塞 I/O（`AsyncSession` + `aiomysql`、`httpx.AsyncClient`、`ChatOpenAI.ainvoke`），多下游独立查询使用 `asyncio.gather` 并发，禁止混入同步阻塞调用；对前端仍保持 `POST /api/chat` 同步 HTTP JSON 响应契约。

---

## 阶段 1：环境核查、配置与数据模型层

- [x] **T1.1 只读核查 MySQL 真实表枚举并固化常量**
  - **目标**：只读查询 `bank_account`、`support_ticket`、`dim_channel` 等表字段约束（`SHOW COLUMNS`），确认 `account_status` 与 `ticket_type` 合法枚举值，杜绝臆测。
  - **涉及文件**：`chat_app/__init__.py`、`chat_app/constants.py`
  - **核心内容**：固化账户状态枚举、工单类型枚举、默认渠道 `MOBILE_BANK`、确定性确认/取消关键词集合、任务类型与意图白名单常量。
  - **验证命令**：`uv run ruff check chat_app && uv run pyright chat_app`

- [x] **T1.2 应用配置管理模块**
  - **目标**：基于 `pydantic-settings` 统一读取 `.env` 配置并兼容连接串格式。
  - **涉及文件**：`chat_app/config.py`、`tests/chat_app/test_config.py`
  - **核心内容**：加载 `CHAT_APP_HOST`（`127.0.0.1`）、`CHAT_APP_PORT`（`8001`）、`BANK_API_BASE_URL`（`http://127.0.0.1:8000`）、`DATABASE_URL`、`LLM_*`、`CHAT_HISTORY_WINDOW`（`20`）、`CHAT_SESSION_TTL_SECONDS`（`3600`）。
  - **验证命令**：`uv run pytest tests/chat_app/test_config.py`

- [x] **T1.3 SQLAlchemy 2.0 异步引擎与 ORM 表模型**
  - **目标**：定义客服专属两张表模型与自动建表能力（不碰任何中台业务表）。
  - **涉及文件**：`chat_app/db/__init__.py`、`chat_app/db/engine.py`、`chat_app/db/models.py`、`tests/chat_app/test_models.py`
  - **核心内容**：实现 `AsyncEngine`、`async_sessionmaker`、`init_db()`；定义 `ChatSession`（含 `session_id`、`status`、`turn_count`、`last_active_at`、`cached_object_json`、`task_state_json` 及联合索引）与 `ChatMessage`（含 `session_id`、`turn_no`、`role`、`content_type`、`intent_category`、`intent_detail`）。
  - **验证命令**：`uv run pytest tests/chat_app/test_models.py`

- [x] **T1.4 会话与消息数据访问层（Repository）**
  - **目标**：封装会话生命周期（1 小时超时切分）与消息持久化读写操作。
  - **涉及文件**：`chat_app/db/repository.py`、`tests/chat_app/test_repository.py`
  - **核心内容**：实现 `get_or_create_active_session`（超时 > 1 小时将旧会话置 `expired` 并创建新 `active` 会话）、`get_active_session_if_valid`（供 `/api/chat/history` 使用）、`get_recent_messages`（滑动窗口）、`save_turn`（事务性写入用户/机器人消息并递增 `turn_count`、更新 `last_active_at` 与状态）。
  - **验证命令**：`uv run pytest tests/chat_app/test_repository.py`

---

## 阶段 2：接口 Schema 与中台 HTTP 客户端

- [ ] **T2.1 对外 API 请求与响应 Schema**
  - **目标**：定义严格对齐 `web/src/App.vue` 的 Pydantic 模型。
  - **涉及文件**：`chat_app/schemas/__init__.py`、`chat_app/schemas/chat.py`、`tests/chat_app/test_schemas_chat.py`
  - **核心内容**：`ObjectPayload`（`type` 仅允许 `account`/`transaction`）、`ChatRequest`（校验 `text` 与 `object` 至少提供一个）、`BotMessage`、`ChatResponse`、`HistoryMessage`（支持 `divider`）、`HistoryResponse`。
  - **验证命令**：`uv run pytest tests/chat_app/test_schemas_chat.py`

- [ ] **T2.2 NLU 结构与双区任务状态 Schema**
  - **目标**：定义意图识别输出模型与双区任务调度对象结构。
  - **涉及文件**：`chat_app/schemas/nlu.py`、`tests/chat_app/test_schemas_nlu.py`
  - **核心内容**：`IntentItem`、`NLUSlots`、`NLUResult`、`TaskItem`（`task_type`、`stage`、`slots`、`missing_slots`）、`TaskState`（`active_task` + `suspended_tasks` 暂缓区栈）。
  - **验证命令**：`uv run pytest tests/chat_app/test_schemas_nlu.py`

- [ ] **T2.3 中台异步 HTTP 客户端（BankClient）**
  - **目标**：封装调用 `app/` 中台的全部 9 个核心接口，统一鉴权、幂等与错误处理。
  - **涉及文件**：`chat_app/clients/__init__.py`、`chat_app/clients/bank_client.py`、`tests/chat_app/test_bank_client.py`
  - **核心内容**：透传 `Authorization: Bearer <sender_id>`、`X-Channel-Code: MOBILE_BANK`、`X-Request-Id`；实现账户列表/详情、交易明细/详情、变更账户状态（含 `request_no`）、`foundation` 5 个配置接口、创建客服工单；捕获超时与非 `code == 0` 响应并转为友好中文业务异常（`BankClientError`）。
  - **验证命令**：`uv run pytest tests/chat_app/test_bank_client.py`

---

## 阶段 3：LLM 封装、Prompt 模板与防幻觉校验器

- [ ] **T3.1 LLM 客户端封装**
  - **目标**：基于 `langchain-openai` 的 `ChatOpenAI` 提供轻量异步调用接口，便于单测注入 Mock。
  - **涉及文件**：`chat_app/llm/__init__.py`、`chat_app/llm/client.py`、`tests/chat_app/test_llm_client.py`
  - **核心内容**：封装 `LLMClient.ainvoke(messages)`，读取 `.env` 中的 `LLM_MODEL`、`LLM_BASE_URL`、`LLM_API_KEY`，处理超时与调用异常。
  - **验证命令**：`uv run pytest tests/chat_app/test_llm_client.py`

- [ ] **T3.2 Prompt 模板集中管理**
  - **目标**：编写结构清晰、输出格式受控的 Prompt 模板。
  - **涉及文件**：`chat_app/llm/prompts.py`
  - **核心内容**：① NLU 意图分类（三大顶层意图 + 槽位 JSON 输出约束 + 历史窗口与当前任务上下文注入）；② S4 中台规则问答 Prompt（严禁编造费率限额）；③ 轻量闲聊与引导 Prompt。
  - **验证命令**：`uv run ruff check chat_app/llm/prompts.py && uv run pyright chat_app/llm/prompts.py`

- [ ] **T3.3 NLU JSON 解析与防幻觉风控校验器**
  - **目标**：实现代码级 JSON 清洗、反序列化与单意图/白名单风控校验。
  - **涉及文件**：`chat_app/llm/parser.py`、`tests/chat_app/test_nlu_parser.py`
  - **核心内容**：剥离 Markdown 代码块并 `json.loads`；校验 `len(intents) == 1`、白名单枚举合法性、置信度阈值、槽位合法性；区分 `ambiguous` / `multi_intent_conflict` / `out_of_scope` / `invalid_schema` 并返回对应中文澄清回复。
  - **验证命令**：`uv run pytest tests/chat_app/test_nlu_parser.py`

---

## 阶段 4：双区任务调度器与对象卡片分支

- [ ] **T4.1 槽位规格与纯代码固定追问模板**
  - **目标**：以纯代码定义各业务任务的必填槽位与零延迟中文追问模板。
  - **涉及文件**：`chat_app/orchestrator/__init__.py`、`chat_app/orchestrator/slot_templates.py`、`tests/chat_app/test_slot_templates.py`
  - **核心内容**：定义各 `task_type` 必填槽位映射、`object.type ↔ slot_name` 映射、计算 `missing_slots`、生成缺失槽位追问文案与冻结/挂失二次确认摘要文案。
  - **验证命令**：`uv run pytest tests/chat_app/test_slot_templates.py`

- [ ] **T4.2 双区任务调度管理器（Active + Suspended）**
  - **目标**：实现 `task_state_json` 的核心状态流转逻辑。
  - **涉及文件**：`chat_app/orchestrator/task_manager.py`、`tests/chat_app/test_task_manager.py`
  - **核心内容**：启动/更新 `active_task`、新任务切入时将原任务压入 `suspended_tasks` 暂缓区、完成或取消后自动弹出恢复原任务、融合 `cached_object_json` 自动填槽、生成并持久化幂等 `request_no`。
  - **验证命令**：`uv run pytest tests/chat_app/test_task_manager.py`

- [ ] **T4.3 对象卡片处理分支（Object Branch）**
  - **目标**：实现前端发送 `account`/`transaction` 卡片的独立处理逻辑。
  - **涉及文件**：`chat_app/orchestrator/handlers/__init__.py`、`chat_app/orchestrator/handlers/object_card.py`、`tests/chat_app/test_handler_object_card.py`
  - **核心内容**：无运行任务时更新 `cached_object_json` 并返回引导回复；处于 `collecting_slots` 时校验对象类型与 `missing_slots` 是否匹配——匹配则自动填槽并推进，不匹配或处于 `awaiting_confirm` 时返回明确澄清提示。
  - **验证命令**：`uv run pytest tests/chat_app/test_handler_object_card.py`

---

## 阶段 5：五大业务场景与闲聊 Handler

- [ ] **T5.1 S1 账户与余额查询 Handler**
  - **涉及文件**：`chat_app/orchestrator/handlers/account.py`、`tests/chat_app/test_handler_account.py`
  - **核心内容**：按需调用 `list_customer_accounts` 或 `get_account`（结合指定/缓存 `account_no`），输出清晰中文余额、币种、冻结金额与状态汇总。
  - **验证命令**：`uv run pytest tests/chat_app/test_handler_account.py`

- [ ] **T5.2 S2 交易明细与单笔交易查询 Handler**
  - **涉及文件**：`chat_app/orchestrator/handlers/transaction.py`、`tests/chat_app/test_handler_transaction.py`
  - **核心内容**：查明细时若未指定 `account_no`，优先取缓存账户，其次查名下账户（仅 1 个自动带出，多个时进入 `collecting_slots` 追问）；查单笔详情调用 `get_transaction`；格式化最近交易列表。
  - **验证命令**：`uv run pytest tests/chat_app/test_handler_transaction.py`

- [ ] **T5.3 S3 账户冻结与挂失 Handler**
  - **涉及文件**：`chat_app/orchestrator/handlers/status_change.py`、`tests/chat_app/test_handler_status_change.py`
  - **核心内容**：校验 `account_no` / `target_status` / `reason` 必填槽位（单账户可自动带出并在确认语明示）；槽位齐全后置 `awaiting_confirm` 并生成固定幂等 `request_no`；确认后调用 `POST /api/v1/accounts/{account_no}/status-changes` 并清理任务。
  - **验证命令**：`uv run pytest tests/chat_app/test_handler_status_change.py`

- [ ] **T5.4 S4 中台规则实时查询 Handler（`knowledge_query`）**
  - **涉及文件**：`chat_app/orchestrator/handlers/faq.py`、`tests/chat_app/test_handler_faq.py`
  - **核心内容**：按 `faq_topic` 路由或通过 `asyncio.gather` 并发调用中台 `account-products` / `service-products` / `channels` / `currencies` / `branches`，将真实结构化数据注入 Prompt 由 LLM 异步生成准确中文回复（不影响当前 `active_task`）。
  - **验证命令**：`uv run pytest tests/chat_app/test_handler_faq.py`

- [ ] **T5.5 S5 转人工创建工单 Handler**
  - **涉及文件**：`chat_app/orchestrator/handlers/handoff.py`、`tests/chat_app/test_handler_handoff.py`
  - **核心内容**：归纳用户诉求与幂等 `request_no`，调用 `POST /api/v1/support/tickets` 创建中台工单并返回工单号 `ticket_no`；建单后清空当前转人工任务，**不锁死会话**。
  - **验证命令**：`uv run pytest tests/chat_app/test_handler_handoff.py`

- [ ] **T5.6 闲聊与引导 Handler（`chitchat`）**
  - **涉及文件**：`chat_app/orchestrator/handlers/chitchat.py`、`tests/chat_app/test_handler_chitchat.py`
  - **核心内容**：响应礼貌寒暄并自然引导银行业务，保持当前 `active_task` 不变（若存在活跃任务可在末尾轻提醒）。
  - **验证命令**：`uv run pytest tests/chat_app/test_handler_chitchat.py`

---

## 阶段 6：对话主编排引擎与 FastAPI 服务装配

- [ ] **T6.1 对话主编排引擎（ChatOrchestrator）**
  - **涉及文件**：`chat_app/orchestrator/engine.py`、`tests/chat_app/test_engine.py`
  - **核心内容**：完整串联 `SPEC.md` 第 3.2 节流程图：1 小时会话超时切分 → Text/Object 分流 → 取消/确认前置拦截 → NLU 识别与防幻觉校验（含解析失败重试 1 次）→ 双区任务调度与 Handler 分发 → 事务性持久化消息与会话状态。
  - **验证命令**：`uv run pytest tests/chat_app/test_engine.py`

- [ ] **T6.2 对外 API 路由层**
  - **涉及文件**：`chat_app/routers/__init__.py`、`chat_app/routers/chat.py`、`tests/chat_app/test_router_chat.py`
  - **核心内容**：实现 `POST /api/chat` 与 `GET /api/chat/history?sender_id=...`（仅返回 1 小时内 `active` 会话消息，非空时末尾追加 `{role: "divider", text: "以上为历史消息"}`，空或超时返回 `{"messages": []}`）。
  - **验证命令**：`uv run pytest tests/chat_app/test_router_chat.py`

- [ ] **T6.3 FastAPI 应用入口与生命周期装配**
  - **涉及文件**：`chat_app/main.py`、`tests/chat_app/test_main.py`
  - **核心内容**：实现 `lifespan`（启动自动建表 `init_db()`、初始化共享 `httpx.AsyncClient` 与关闭清理）、`GET /health`、全局异常兜底（统一返回 `{"detail": "..."}`）、`uvicorn` 启动入口（`127.0.0.1:8001`）。
  - **验证命令**：`uv run pytest tests/chat_app/test_main.py`

---

## 阶段 7：静态检查回归与三端联调验收

- [ ] **T7.1 全量质量门禁与单元测试回归**
  - **目标**：确保所有新增代码零 Lint 错误、零类型报错、全量单元测试通过。
  - **验证命令**：`uv run ruff check chat_app tests && uv run pyright chat_app && uv run pytest`

- [ ] **T7.2 三端启动联调与 MVP 5 大场景验收**
  - **目标**：配合已启动的中台 `app:8000` 与前端 `web:5173`，启动 `chat_app:8001`，端到端验证 `GET /health`、1 小时会话与历史加载、卡片填槽/不匹配澄清、双区任务挂起恢复、5 大核心场景全通，并更新 `PROGRESS.md` 归档。
  - **验证方式**：启动服务 `uv run -m chat_app.main` + 接口冒烟脚本/前端实测验证。
