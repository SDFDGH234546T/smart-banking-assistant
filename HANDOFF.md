# 项目交接文档（HANDOFF）

## 1. 当前进度
- **已完成里程碑**：
  - **阶段 1（环境核查、配置与数据模型层）全部完成**（`T1.1` ~ `T1.4` 已验收通过并归档至 `PROGRESS.md` 与 `docs/stage1_summary.md`）。
  - **阶段 2 已完成 1 项**：`T2.2`（NLU 结构与双区任务状态 Schema）。
- **PLAN.md 状态**：`T1.1`、`T1.2`、`T1.3`、`T1.4`、`T2.2` 已勾选 `[x]`；其余子任务（`T2.1`、`T2.3` 及阶段 3~7）待执行。
- **下一个待执行任务**：**`T2.1` 对外 API 请求与响应 Schema**（创建 `chat_app/schemas/chat.py` 与 `tests/chat_app/test_schemas_chat.py`，并在 `chat_app/schemas/__init__.py` 补充导出；随后执行 `T2.3` 中台异步 HTTP 客户端）。

## 2. 核心约定与决策
- **工程与部署边界**：
  - 在当前仓库新增独立包 `chat_app/`，复用根目录 `.venv`（Python `>=3.12`、`uv`）与现有 MySQL，监听 `127.0.0.1:8001`。
  - **禁止修改 `app/`（中台 8000）与 `web/`（前端 5173）现有代码**；严格对齐 `web/src/App.vue` 的非流式同步 JSON 契约（`GET /health`、`GET /api/chat/history`、`POST /api/chat`）。
  - **全链路异步 I/O 规范**：异步仅指 `chat_app/` 后端内部全链路 `async/await` 非阻塞调用（`AsyncSession` + `aiomysql`、`httpx.AsyncClient`、`ChatOpenAI.ainvoke`），多下游独立查询使用 `asyncio.gather` 并发，严禁混用同步阻塞库（如 `pymysql`、`requests`、`time.sleep`、同步 `invoke`）；对前端保持同步 HTTP JSON 契约不变。
- **MVP 业务范围（5 大场景）**：
  - 做：S1 账户/余额查询、S2 交易明细/单笔查询、S3 账户冻结/挂失（多轮填槽 + 二次确认）、S4 银行业务规则问答（**不建本地知识库，实时调用 `app/` 的 `foundation` 接口**）、S5 转人工（调用 `POST /api/v1/support/tickets` 建单，**建单后不锁死会话**）。
  - 明确不做：理财/贷款/还款/风控/催收/对账模块、资金动账写操作、SSE 流式、向量库 RAG、人工坐席端、Summary 摘要压缩。
- **阶段 1 已落地的实现约定（后续模块必须遵循）**：
  - **库表枚举核查结论**：`bank_account.account_status` 与 `support_ticket.ticket_type` 均为 `varchar(64)`；全量账户状态集合为 `normal`/`active`/`frozen`/`lost`/`closed`，S3 变更目标状态严格白名单为 `frozen`/`lost`；工单默认类型 `general_inquiry`、`related_type="none"`；`dim_channel` 已确认存在 `MOBILE_BANK`。
  - **配置与连接串**：`Settings` 设置 `extra="ignore"` 忽略中台 `.env` 字段，强制显式配置 `DATABASE_URL`（不回退 `DB_*`），自动将 `mysql://` / `mysql+pymysql://` 转为 `mysql+aiomysql://`；`LLM_API_KEY` 允许默认空串以利离线单测；已预留 `BANK_API_TIMEOUT_SECONDS=10.0` 与 `LLM_TIMEOUT_SECONDS=30.0`；通过 `@lru_cache get_settings()` 延迟加载。
  - **数据库与时间口径**：统一使用 `Asia/Shanghai` 本地无时区时间（`chat_app.db.models.local_now()`），与中台 `app/utils.py` 一致；`AsyncEngine` 与 `async_sessionmaker` 延迟初始化（`pool_pre_ping=True`、`pool_recycle=3600`、`expire_on_commit=False`）；`task_state_json` 使用 `default_task_state` 工厂函数防可变对象共享。
  - **Repository 读写边界**：`get_active_session_if_valid` 保持纯只读不写库（超时仅返回 `None`）；`get_or_create_active_session` 负责超时切换并将所有旧 `active` 统一置为 `expired`；`save_turn` 接收单条 `bot_text` 字符串并在同一事务内原子落库消息与会话状态，通过 `update_cached_object` 标志位防误覆写缓存卡片。
  - **NLU Schema 分层**：`IntentItem.task_type` 保留为 `str | None`（供 `T3.3` `llm/parser.py` 精准区分 `out_of_scope` 与 `invalid_schema`），`NLUSlots` 负责空白字符串归 `None` 与 `target_status`/`transaction_type`/`limit`（`1~50`）校验。
- **开发规范（`AGENTS.md`）**：
  - Vibe Coding 模式：动手前用 2~3 句话讲清思路再编码；关键架构分歧留选择题；每次仅执行指定单个子任务，完成后验证、勾选 `PLAN.md`、按规定格式汇报并停止。
  - 代码注释规范：核心逻辑必须补充简洁中文注释，遵循“写 Why（为什么），不写 What（语法在干嘛）”。
  - 单元测试统一纯离线 Mock（不依赖真实 DB、LLM 与中台 8000 服务），阶段 7 再做三端真实联调。

## 3. 关键变更文件
- **项目文档**：
  - `SPEC.md`、`PLAN.md`、`HANDOFF.md`、`AGENTS.md`、`PROGRESS.md`、`LESSONS.md`、`docs/stage1_summary.md`
- **业务代码（`chat_app/`）**：
  - `chat_app/__init__.py`、`chat_app/constants.py`（T1.1）
  - `chat_app/config.py`（T1.2）
  - `chat_app/db/__init__.py`、`chat_app/db/models.py`、`chat_app/db/engine.py`（T1.3）
  - `chat_app/db/repository.py`（T1.4）
  - `chat_app/schemas/__init__.py`、`chat_app/schemas/nlu.py`（T2.2）
- **单元测试（`tests/chat_app/`）**：
  - `tests/chat_app/test_config.py`（6 用例）
  - `tests/chat_app/test_models.py`（6 用例）
  - `tests/chat_app/test_repository.py`（5 用例）
  - `tests/chat_app/test_schemas_nlu.py`（9 用例）

## 4. 环境注意事项与待办
- **环境避坑（已同步至 `LESSONS.md`）**：
  - **Pyright 解释器**：直接运行 `.venv\Scripts\pyright.exe` 会回退全局 Python 报 `reportMissingImports`，必须显式传入 `--pythonpath .venv\Scripts\python.exe`。
  - **Windows 沙盒限制**：沙盒内 `uv` 缓存目录可能触发权限拒绝，静态检查可直接调用 `.venv\Scripts\ruff.exe` / `.venv\Scripts\pyright.exe`；含 `@pytest.mark.anyio` 或 `asyncio.run` 的异步单测在沙盒内会因本地 `socketpair` 被拦截而挂起，需在沙盒外运行（`BypassSandbox: true`）。
  - **依赖现状**：`.venv` 已安装 `cryptography`（`aiomysql` 连 MySQL 8 `caching_sha2_password` 认证就绪）；未安装 `aiosqlite`，数据库层单测统一采用离线 Mock + MySQL 方言 DDL 编译校验。
- **后续关键待办**：
  - 按 `PLAN.md` 继续推进 `T2.1`（对外 API Schema）与 `T2.3`（中台异步 `BankClient`），完成阶段 2 后归档至 `PROGRESS.md`。
  - 阶段 7（`T7.2`）再执行真实 MySQL 自动建表 `init_db()` 及 `app:8000` + `chat_app:8001` + `web:5173` 三端联调。

## 5. 验收状态
- **当前验收状态**：已落地模块的 **26 个单元测试全部通过**，Ruff 与 Pyright 均为 **0 errors, 0 warnings**（服务入口 `chat_app/main.py` 尚未到阶段 6 实现）。
- **常用验证命令（PowerShell 5.1）**：
  - 代码规范检查：`.venv\Scripts\ruff.exe check chat_app tests`
  - 类型检查：`.venv\Scripts\pyright.exe --pythonpath .venv\Scripts\python.exe chat_app`
  - 单元测试（含异步测试需在沙盒外执行）：`.venv\Scripts\pytest.exe tests/chat_app/`
  - 启动客服后端（阶段 6 完成后）：`uv run -m chat_app.main`
