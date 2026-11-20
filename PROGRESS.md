# 开发进度归档（PROGRESS）

## 阶段 1：环境核查、配置与数据模型层（已完成）

### 已完成子任务
- **T1.1**：只读核查 MySQL `bank_account`、`support_ticket`、`dim_channel` 字段枚举，固化 [chat_app/constants.py](file:///d:/0708/尚硅谷大模型项目实战之掌柜小二实战/finance-data/chat_app/constants.py) 常量与白名单。
- **T1.2**：实现 [chat_app/config.py](file:///d:/0708/尚硅谷大模型项目实战之掌柜小二实战/finance-data/chat_app/config.py)（`Settings` + `get_settings()`），支持 `DATABASE_URL` 同步前缀转异步及 `.env` 无关变量忽略。
- **T1.3**：实现 [chat_app/db/models.py](file:///d:/0708/尚硅谷大模型项目实战之掌柜小二实战/finance-data/chat_app/db/models.py) 与 [chat_app/db/engine.py](file:///d:/0708/尚硅谷大模型项目实战之掌柜小二实战/finance-data/chat_app/db/engine.py)（`ChatSession` / `ChatMessage`、`AsyncEngine`、`init_db()`、`dispose_engine()`）。
- **T1.4**：实现 [chat_app/db/repository.py](file:///d:/0708/尚硅谷大模型项目实战之掌柜小二实战/finance-data/chat_app/db/repository.py)（1 小时超时会话切分、只读有效会话查询、滑动窗口消息拉取、原子轮次落库）。

### 关键变动与验收
- 全部采用全链路异步 I/O 与 `Asia/Shanghai` 无时区本地时间口径。
- 单元测试（`test_config.py`、`test_models.py`、`test_repository.py`）与 `ruff`、`pyright` 静态检查均已通过。

---

## 阶段 2：接口 Schema 与中台 HTTP 客户端（已完成）

### 已完成子任务
- **T2.1**：实现 [chat_app/schemas/chat.py](file:///d:/0708/尚硅谷大模型项目实战之掌柜小二实战/finance-data/chat_app/schemas/chat.py)，定义严格对齐前端 `App.vue` 的 `ObjectPayload`、`ChatRequest`、`BotMessage`、`ChatResponse`、`HistoryMessage`（含 `divider`）与 `HistoryResponse`。
- **T2.2**：实现 [chat_app/schemas/nlu.py](file:///d:/0708/尚硅谷大模型项目实战之掌柜小二实战/finance-data/chat_app/schemas/nlu.py)，定义 `IntentItem`（保留 `str | None` 供后续防幻觉分类）、`NLUSlots`（空白归一化与白名单校验）、`NLUResult`、`TaskItem` 与 `TaskState`（`active_task` + `suspended_tasks`）。
- **T2.3**：实现 [chat_app/clients/bank_client.py](file:///d:/0708/尚硅谷大模型项目实战之掌柜小二实战/finance-data/chat_app/clients/bank_client.py)，注入共享 `httpx.AsyncClient` 封装中台账户、交易、状态变更、5 个 `foundation` 配置查询及工单创建接口，统一透传鉴权/渠道/追踪头并转译 `BankClientError`。

### 关键变动与验收
- 阶段 2 单元测试（`test_schemas_chat.py`、`test_schemas_nlu.py`、`test_bank_client.py`）与 `ruff`、`pyright` 静态检查均已通过。

---

## 阶段 3：LLM 封装、Prompt 模板与防幻觉校验器（已完成）

### 已完成子任务
- **T3.1**：实现 [chat_app/llm/client.py](file:///d:/0708/尚硅谷大模型项目实战之掌柜小二实战/finance-data/chat_app/llm/client.py)，基于 `langchain-openai` 的 `ChatOpenAI.ainvoke` 封装轻量异步 `LLMClient`（支持单测注入 Mock 模型），统一处理缺省密钥、超时与异常并转译为 `LLMClientError`。
- **T3.2**：实现 [chat_app/llm/prompts.py](file:///d:/0708/尚硅谷大模型项目实战之掌柜小二实战/finance-data/chat_app/llm/prompts.py)，集中管理 NLU 意图/槽位抽取、S4 中台规则问答（严禁编造费率限额）与轻量闲聊引导三套 Prompt 模板。
- **T3.3**：实现 [chat_app/llm/parser.py](file:///d:/0708/尚硅谷大模型项目实战之掌柜小二实战/finance-data/chat_app/llm/parser.py)，剥离 Markdown 代码块并完成 JSON 解析、单意图唯一性、白名单与置信度阈值校验，精确区分 `ambiguous`、`multi_intent_conflict`、`out_of_scope` 与 `invalid_schema`。

### 关键变动与验收
- 阶段 3 单元测试（`test_llm_client.py`、`test_nlu_parser.py`）与 `ruff`、`pyright` 静态检查均已通过。


---

## 阶段 4：双区任务调度器与对象卡片分支（已完成）

### 已完成子任务
- **T4.1**：实现 [chat_app/orchestrator/slot_templates.py](file:///d:/0708/尚硅谷大模型项目实战之掌柜小二实战/finance-data/chat_app/orchestrator/slot_templates.py)，以纯代码固化各任务必填槽位映射（`REQUIRED_SLOTS`）、卡片类型到槽位映射（`OBJECT_TYPE_TO_SLOT`）、缺失槽位计算及零 LLM 延迟追问/二次确认摘要模板。
- **T4.2**：实现 [chat_app/orchestrator/task_manager.py](file:///d:/0708/尚硅谷大模型项目实战之掌柜小二实战/finance-data/chat_app/orchestrator/task_manager.py)，封装 `active_task` 与 `suspended_tasks` 双区栈调度、新任务打断压栈与完成/取消自动弹出恢复、显式槽位优先融合 `cached_object_json`，以及敏感写操作固定幂等 `request_no` 生成。
- **T4.3**：实现 [chat_app/orchestrator/handlers/object_card.py](file:///d:/0708/尚硅谷大模型项目实战之掌柜小二实战/finance-data/chat_app/orchestrator/handlers/object_card.py)，完成前端 `account`/`transaction` 卡片双分流：无任务时缓存引导、填槽期精确匹配并推进任务（含 `ready_to_execute_task` 标记），以及不匹配或待确认态的保护与中文澄清。

### 关键变动与验收
- 阶段 4 单元测试（`test_slot_templates.py`、`test_task_manager.py`、`test_handler_object_card.py`）与全量 51 个单元测试均通过，`ruff` 与 `pyright` 静态检查 0 报错。

---

## 阶段 5：五大业务场景与闲聊 Handler（已完成）

### 已完成子任务
- **T5.1**：实现 [chat_app/orchestrator/handlers/account.py](file:///d:/0708/尚硅谷大模型项目实战之掌柜小二实战/finance-data/chat_app/orchestrator/handlers/account.py)，支持指定/缓存 `account_no` 单账户详情与名下全量账户汇总查询，完成后自动恢复暂缓区任务。
- **T5.2**：实现 [chat_app/orchestrator/handlers/transaction.py](file:///d:/0708/尚硅谷大模型项目实战之掌柜小二实战/finance-data/chat_app/orchestrator/handlers/transaction.py)，支持单笔交易及对账状态查询、近期交易明细查询（单账户自动带出、多账户退回 `collecting_slots` 追问）。
- **T5.3**：实现 [chat_app/orchestrator/handlers/status_change.py](file:///d:/0708/尚硅谷大模型项目实战之掌柜小二实战/finance-data/chat_app/orchestrator/handlers/status_change.py)，完成冻结/挂失填槽（含单账户自动带出）、`awaiting_confirm` 幂等 `request_no` 准备及确认后调用中台写接口执行变更。
- **T5.4**：实现 [chat_app/orchestrator/handlers/faq.py](file:///d:/0708/尚硅谷大模型项目实战之掌柜小二实战/finance-data/chat_app/orchestrator/handlers/faq.py)，按 `faq_topic` 路由或通过 `asyncio.gather` 并发拉取中台 `foundation` 实时配置，注入 Prompt 严禁编造费率限额，且保持 `active_task` 不变。
- **T5.5**：实现 [chat_app/orchestrator/handlers/handoff.py](file:///d:/0708/尚硅谷大模型项目实战之掌柜小二实战/finance-data/chat_app/orchestrator/handlers/handoff.py)，归纳诉求并携带幂等号创建中台工单，返回 `ticket_no` 后清空当前任务且不锁死会话。
- **T5.6**：实现 [chat_app/orchestrator/handlers/chitchat.py](file:///d:/0708/尚硅谷大模型项目实战之掌柜小二实战/finance-data/chat_app/orchestrator/handlers/chitchat.py)，响应礼貌寒暄并保留 `active_task` 轻提醒。

### 关键变动与验收
- 阶段 5 全部 11 个新增业务单测及全量 62 个单元测试均通过，`ruff` 与 `pyright` 静态检查 0 报错。

---

## 阶段 6：对话主编排引擎与 FastAPI 服务装配（已完成）

### 已完成子任务
- **T6.1**：实现 [chat_app/orchestrator/engine.py](file:///d:/0708/尚硅谷大模型项目实战之掌柜小二实战/finance-data/chat_app/orchestrator/engine.py)（`ChatOrchestrator`），完整串联 1 小时会话超时切分、Text/Object 双分流、取消/确认确定性前置拦截、NLU 识别（含 `invalid_schema` 重试 1 次）、双区任务调度与 Handler 分发、下游异常兜底及事务性 `save_turn` 持久化。
- **T6.2**：实现 [chat_app/routers/chat.py](file:///d:/0708/尚硅谷大模型项目实战之掌柜小二实战/finance-data/chat_app/routers/chat.py) 与 [chat_app/routers/__init__.py](file:///d:/0708/尚硅谷大模型项目实战之掌柜小二实战/finance-data/chat_app/routers/__init__.py)，提供 `POST /api/chat` 与 `GET /api/chat/history`（非空时末尾追加 `以上为历史消息` 分割线）。
- **T6.3**：实现 [chat_app/main.py](file:///d:/0708/尚硅谷大模型项目实战之掌柜小二实战/finance-data/chat_app/main.py)，装配 `lifespan`（`init_db()` 自动建表、共享 `httpx.AsyncClient` 与 `ChatOrchestrator` 注入及关闭释放）、`GET /health`、全局 `{"detail": "..."}` 异常兜底与 `uvicorn` 启动入口（`127.0.0.1:8001`）。

### 关键变动与验收
- 阶段 6 新增 8 个单元测试（`test_engine.py`、`test_router_chat.py`、`test_main.py`）与全量 70 个单元测试均通过，`ruff` 与 `pyright` 静态检查 0 报错。

---

## 阶段 7：静态检查回归与三端联调验收（已完成）

### 已完成子任务
- **T7.1**：完成全量质量门禁回归（`ruff` 0 警告、`pyright` 0 报错、全量 70 个单元测试通过）。
- **T7.2**：启动 `app:8000`、`chat_app:8001` 与 `web:5173` 完成三端真实联调验收，端到端跑通 `GET /health`、`GET /api/chat/history`（含 `以上为历史消息` 分割线）、对象卡片缓存/匹配填槽/不匹配澄清、双区任务挂起与自动恢复，以及 S1~S5 五大业务场景（含真实 MySQL 与 DashScope LLM 联动）。

### 关键变动与验收
- 联调中定位并修复两项真实集成问题：
  1. [chat_app/constants.py](file:///d:/0708/尚硅谷大模型项目实战之掌柜小二实战/finance-data/chat_app/constants.py) 与 [chat_app/clients/bank_client.py](file:///d:/0708/尚硅谷大模型项目实战之掌柜小二实战/finance-data/chat_app/clients/bank_client.py)：为 `create_support_ticket` 透传默认 `X-Operator-No: EMP000001`，解决客户态调用中台建单接口报 `403 EMPLOYEE_NOT_AVAILABLE` 问题。
  2. [chat_app/llm/prompts.py](file:///d:/0708/尚硅谷大模型项目实战之掌柜小二实战/finance-data/chat_app/llm/prompts.py)：明确 NLU 仅针对本轮用户输入识别意图（不重复输出上下文活跃任务）且多知识库主题咨询合并为单意图，打通业务打断挂起与规则问答并发。
- 经验沉淀已追加至 [LESSONS.md](file:///d:/0708/尚硅谷大模型项目实战之掌柜小二实战/finance-data/LESSONS.md)。
