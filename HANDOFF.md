# 项目交接文档（HANDOFF）

## 1. 当前进度
- **已完成里程碑**：
  - **阶段 1（环境核查、配置与数据模型层）**：`T1.1` ~ `T1.4` 全部完成并归档至 `PROGRESS.md`。
  - **阶段 2（接口 Schema 与中台 HTTP 客户端）**：`T2.1` ~ `T2.3` 全部完成并归档至 `PROGRESS.md`。
  - **阶段 3（LLM 封装、Prompt 模板与防幻觉校验器）**：`T3.1` ~ `T3.3` 全部完成并归档至 `PROGRESS.md`。
- **PLAN.md 状态**：`T1.1` ~ `T3.3` 均已勾选 `[x]`；阶段 4 ~ 7（`T4.1` ~ `T7.2`）待执行。
- **下一个待执行任务**：**`T4.1` 槽位规格与纯代码固定追问模板**（创建 `chat_app/orchestrator/__init__.py`、`chat_app/orchestrator/slot_templates.py` 与 `tests/chat_app/test_slot_templates.py`）。

## 2. 核心约定与决策
- **工程与部署边界**：
  - 独立包 `chat_app/` 监听 `127.0.0.1:8001`，复用根目录 `.venv`（Python `>=3.12`、`uv`）与现有 MySQL。
  - **禁止修改 `app/`（中台 8000）与 `web/`（前端 5173）现有代码**；严格对齐 `web/src/App.vue` 的非流式同步 JSON 契约（`GET /health`、`GET /api/chat/history`、`POST /api/chat`）。
  - **全链路异步 I/O 规范**：`chat_app/` 内部严格使用 `async/await`（`AsyncSession` + `aiomysql`、`httpx.AsyncClient`、`ChatOpenAI.ainvoke`），多下游独立查询用 `asyncio.gather` 并发，禁止混用同步阻塞库（`pymysql`/`requests`/`time.sleep`/同步 `invoke`）。
- **MVP 业务范围与不做项**：
  - 做：S1 账户/余额查询、S2 交易明细/单笔查询、S3 账户冻结/挂失（填槽 + 二次确认）、S4 银行业务规则问答（实时调用 `app/` `foundation` 接口）、S5 转人工建单（**建单后不锁死会话**）。
  - 明确不做：理财/贷款/还款/风控/催收/对账、资金动账写操作、SSE 流式、向量库 RAG、人工坐席端、Summary 摘要压缩。
- **已落地的模块接口与设计约定**：
  - **库表枚举**：`bank_account.account_status` 与 `support_ticket.ticket_type` 均为 `varchar(64)`；全量状态 `{normal, active, frozen, lost, closed}`，S3 变更目标状态仅允许 `{frozen, lost}`；工单默认 `ticket_type="general_inquiry"`、`related_type="none"`；默认渠道 `MOBILE_BANK`。
  - **Schema 校验边界（阶段 2）**：`chat.py` 对 `sender_id`/`object.id`/`text` 做空白归一化与 `text`/`object` 至少其一校验；`IntentItem` 故意保留 `category`/`task_type`/`faq_topic` 为 `str | None`，将白名单拦截留给 `llm/parser.py` 以精确区分 `out_of_scope` 与 `invalid_schema`；`TaskItem` 强制校验 `TASK_TYPES` 与 `stage`（`collecting_slots` / `awaiting_confirm`）。
  - **中台客户端（阶段 2）**：`BankClient` 通过外部注入共享 `httpx.AsyncClient` 复用连接池（便于 `lifespan` 管理与 `MockTransport` 单测），统一透传 `Authorization: Bearer <sender_id>`、`X-Channel-Code: MOBILE_BANK`、`X-Request-Id`；所有超时、网络异常、HTTP `>=400` 及 `code != 0` 统一转译为友好中文异常 `BankClientError`；成功时直接解包返回 `data` 字典。
  - **LLM 与防幻觉解析（阶段 3）**：`LLMClient` 延迟实例化 `ChatOpenAI`（支持注入 `chat_model` Mock），超时与异常统一转译为 `LLMClientError`；`parse_nlu_response` 先剥离 Markdown 代码块再按“JSON/Schema → 单意图唯一性（`len(intents)==1`） → 白名单枚举 → `confidence >= 0.6`”校验，未知 `faq_topic` 自动归入 `"general"`。
- **开发规范（`AGENTS.md`）**：核心逻辑必须补充“写 Why 不写 What”的简洁中文注释；单测统一纯离线 Mock；PowerShell 5.1 环境串联命令使用 `;`（不支持 `&&`）。

## 3. 关键变更文件
- **项目文档**：`SPEC.md`、`PLAN.md`、`HANDOFF.md`、`AGENTS.md`、`PROGRESS.md`、`LESSONS.md`、`docs/stage1_summary.md`
- **阶段 1（`chat_app/` 基础层）**：
  - `chat_app/__init__.py`、`chat_app/constants.py`：全局枚举常量、确认/取消关键词与白名单集合。
  - `chat_app/config.py`：基于 `pydantic-settings` 加载 `.env` 配置并兼容转换异步 `DATABASE_URL`。
  - `chat_app/db/models.py`、`chat_app/db/engine.py`、`chat_app/db/repository.py`：异步 ORM 表模型（`ChatSession`/`ChatMessage`）、引擎生命周期及 1 小时超时切分/原子落库 CRUD。
- **阶段 2（Schema 与中台客户端）**：
  - `chat_app/schemas/chat.py`、`chat_app/schemas/__init__.py`：对齐前端 `App.vue` 的 API 请求/响应与历史分割线 Schema。
  - `chat_app/schemas/nlu.py`：NLU 输出结构（`IntentItem`/`NLUSlots`/`NLUResult`）与双区任务状态（`TaskItem`/`TaskState`）。
  - `chat_app/clients/bank_client.py`、`chat_app/clients/__init__.py`：封装中台账户、交易、状态变更、5 个 `foundation` 接口与工单创建的异步客户端及 `BankClientError`。
- **阶段 3（LLM 与防幻觉校验）**：
  - `chat_app/llm/client.py`、`chat_app/llm/__init__.py`：`ChatOpenAI.ainvoke` 异步封装与 `LLMClientError`。
  - `chat_app/llm/prompts.py`：NLU 意图/槽位抽取、S4 规则问答与闲聊引导 Prompt 模板。
  - `chat_app/llm/parser.py`：NLU JSON 清洗、单意图/白名单/置信度风控校验器与固定中文澄清回复。
- **单元测试（`tests/chat_app/`）**：
  - `test_config.py`（6）、`test_models.py`（6）、`test_repository.py`（5）、`test_schemas_chat.py`（5）、`test_schemas_nlu.py`（4）、`test_bank_client.py`（4）、`test_llm_client.py`（3）、`test_nlu_parser.py`（5）。

## 4. 未解决的问题 / 待办
- **环境注意事项（已同步 `LESSONS.md`）**：
  - **Pyright 解释器**：运行 `.venv\Scripts\pyright.exe` 必须显式传入 `--pythonpath .venv\Scripts\python.exe`，否则会回退系统全局 Python 报 `reportMissingImports`。
  - **Windows 沙盒限制**：含 `@pytest.mark.anyio` 或 `asyncio.run` 的异步单测在沙盒内会因 `socketpair` 被拦截而挂起，运行含异步用例的 `pytest` 必须使用 `BypassSandbox: true`；静态检查直接调用 `.venv\Scripts\ruff.exe` 与 `.venv\Scripts\pyright.exe`。
  - **依赖现状**：`.venv` 未安装 `aiosqlite`，DB 单测继续采用离线 Mock + MySQL DDL 编译校验；真实 MySQL 自动建表 `init_db()` 及三端联调留待阶段 7（`T7.2`）。
- **后续关键待办**：
  - 按 `PLAN.md` 顺序推进阶段 4（`T4.1` 槽位模板 → `T4.2` 双区任务调度器 → `T4.3` 对象卡片分支），完成后归档至 `PROGRESS.md`。

## 5. 验收状态
- **当前验收状态**：阶段 1 ~ 3 全部 **38 个单元测试全数通过**，Ruff 与 Pyright 均为 **0 errors, 0 warnings**（`chat_app/main.py` 将在阶段 6 实现）。
- **常用验证命令（PowerShell 5.1）**：
  - 代码规范检查：`.venv\Scripts\ruff.exe check chat_app tests`
  - 类型检查：`.venv\Scripts\pyright.exe --pythonpath .venv\Scripts\python.exe chat_app`
  - 全量单元测试（沙盒外执行）：`.venv\Scripts\pytest.exe tests/chat_app/`
