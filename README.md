# 智能银行客服系统（Finance Data & Chat Orchestrator）

![Python](https://img.shields.io/badge/Python-3.12%2B-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115%2B-009688?logo=fastapi&logoColor=white)
![Vue](https://img.shields.io/badge/Vue-3.5-4FC08D?logo=vue.js&logoColor=white)
![MySQL](https://img.shields.io/badge/MySQL-8.0-4479A1?logo=mysql&logoColor=white)
![uv](https://img.shields.io/badge/uv-package%20manager-DE5FE9)
![LangChain](https://img.shields.io/badge/LangChain-OpenAI%20Compatible-1C3C3C)
![Ruff](https://img.shields.io/badge/Ruff-lint%20%26%20format-D7FF64?logo=ruff&logoColor=black)

面向零售银行业务场景的智能客服系统：由 **`chat_app/`（智能客服对话编排后端，BFF）** 承接 **`web/`（Vue 3 前端）** 的非流式同步对话与对象卡片交互，并通过异步 HTTP 协议对接 **`app/`（银行业务中台）**，完成账户查询、交易追溯、敏感状态变更、实时业务规则问答与人工工单流转。

---

## 核心亮点与工程特性

- **5 大银行核心业务场景（MVP）**
  - **S1 账户与余额查询**：支持名下全部账户汇总及指定/缓存账户详情（可用余额、冻结金额、币种、状态）。
  - **S2 交易明细与单笔交易查询**：支持指定账户近期交易明细（单账户自动带出，多账户自动追问）及单笔交易对账状态查询。
  - **S3 账户冻结 / 挂失**：强确定性多轮流程，补齐 `account_no`、`target_status`（`frozen`/`lost`）与 `reason` 后生成唯一幂等 `request_no`，必须经用户明确二次确认后方可执行写操作。
  - **S4 银行业务规则实时问答**：基于中台 `foundation` 配置接口实时拉取账户产品限额、服务手续费、支持渠道、币种与网点信息，并发查询（`asyncio.gather`）后注入上下文作答，无需维护易过期的静态 FAQ。
  - **S5 转人工客服（工单流转）**：归纳客户诉求并透传默认员工号 `X-Operator-No` 调用中台创建客服工单，返回 `ticket_no`；建单后不锁死会话，支持继续自助对话。
- **1 小时会话生命周期管理**
  - 基于 `chat_session.last_active_at` 实现 `CHAT_SESSION_TTL_SECONDS`（默认 `3600` 秒）超时切分：超时后自动将旧会话置为 `expired` 并开启新会话（保留历史供审计回溯）；`GET /api/chat/history` 仅返回当前未超时的活跃会话消息，并在末尾追加 `以上为历史消息` 分割线。
- **文本 / 对象卡片双分支路由（Text vs Object）**
  - 接收前端发送的 `account` / `transaction` 对象卡片时走独立编排分支：无活跃任务时写入 `cached_object_json` 并引导后续操作；处于 `collecting_slots` 填槽期且类型匹配时自动填充 `account_no` 或 `transaction_no` 并推进任务；类型不匹配或处于 `awaiting_confirm` 待确认态时保持原状态并输出清晰中文澄清。
- **确定性 NLU 校验与防幻觉机制**
  - `llm/parser.py` 对模型输出执行 Markdown 代码块剥离、JSON 解析与 Pydantic 模型校验，强制实施**单意图唯一性校验**、**顶层意图与任务白名单校验**、**低置信度拦截**与 **1 次 `invalid_schema` 重试**，精确区分 `ambiguous`、`multi_intent_conflict` 与 `out_of_scope`。
- **双区任务调度与零 LLM 延迟追问**
  - 通过 `task_state_json` 维护 `active_task`（活跃任务）与 `suspended_tasks`（栈式暂缓区）：新任务切入自动将原任务压栈暂缓，闲聊（`chitchat`）与规则查询（`knowledge_query`）保持当前活跃任务不中断，任务完成或取消后自动弹出并恢复暂缓任务。
  - 缺失必填槽位时使用 `slot_templates.py` 纯代码固定模板生成追问与二次确认摘要，响应确定且无额外 LLM 耗时。
- **全链路异步 I/O**
  - 路由层、数据库层（SQLAlchemy 2.0 `AsyncSession` + `aiomysql`）、中台 HTTP 客户端（`httpx.AsyncClient`，禁用 `trust_env` 避免本地代理劫持）及 LLM 调用（`ChatOpenAI.ainvoke`）全链路采用非阻塞 `async/await`。

---

## 系统架构与对话流程

### 1. 整体系统架构

```mermaid
flowchart LR
    Web["web/ 前端 (Vue 3 + Vite)<br/>127.0.0.1:5173"] -->|"/api/* & /health"| ChatApp["chat_app/ 客服编排后端 (FastAPI)<br/>127.0.0.1:8001"]
    Web -->|"/bank/* (直连业务展示)"| BankApp["app/ 银行业务中台 (FastAPI)<br/>127.0.0.1:8000"]

    ChatApp -->|"httpx.AsyncClient<br/>Bearer + X-Channel-Code + X-Request-Id"| BankApp
    ChatApp -->|"SQLAlchemy Async + aiomysql<br/>chat_session / chat_message"| MySQL[("MySQL 8.0<br/>中台业务表 + chat_* 客服表")]
    ChatApp -->|"langchain-openai (ainvoke)"| LLM["OpenAI 兼容大模型服务<br/>(如 DashScope qwen-plus)"]
    BankApp -->|"pymysql"| MySQL
```

### 2. 核心对话状态流转（Text vs Object 双分支）

```mermaid
flowchart TD
    A["POST /api/chat (sender_id + text/object)"] --> B{"活跃会话是否存在且 <= 1h?"}
    B -->|否| C["旧会话置 expired -> 新建 active 会话"]
    B -->|是| D["复用当前 active 会话"]
    C --> E{"输入类型"}
    D --> E

    E -->|Object 卡片| O1{"active_task 是否为 collecting_slots?"}
    O1 -->|否| O2["更新 cached_object_json 并引导操作"]
    O1 -->|是| O3{"卡片类型是否匹配缺失槽位?"}
    O3 -->|匹配| O4["自动填槽并推进任务"]
    O3 -->|不匹配/待确认| O5["保留原任务并给出澄清提示"]

    E -->|Text 文本| T0{"前置确定性关键词拦截"}
    T0 -->|取消指令| T_CANCEL["清空 active_task -> 尝试恢复暂缓任务"]
    T0 -->|awaiting_confirm 且确认| T_EXEC["携带幂等 request_no 执行冻结/挂失 -> 尝试恢复暂缓任务"]
    T0 -->|常规/填槽中| T1["NLU 意图识别与槽位抽取"]
    T1 --> T2{"单意图 / 白名单 / 置信度校验"}
    T2 -->|失败| T3["返回针对性澄清 (ambiguous / conflict / out_of_scope)"]
    T2 -->|通过| T4{"顶层意图路由"}
    T4 -->|chitchat| T5["生成礼貌回复 (active_task 不变)"]
    T4 -->|knowledge_query| T6["并发查询中台 foundation 接口 -> LLM 作答 (active_task 不变)"]
    T4 -->|task_flow| T7{"是否与 active_task 同任务?"}
    T7 -->|不同任务| T8["原任务压入 suspended_tasks -> 初始化新任务"]
    T7 -->|无任务或同任务| T9["合并显式槽位与 cached_object_json"]
    T8 --> T10{"missing_slots 是否为空?"}
    T9 --> T10
    O4 --> T10

    T10 -->|非空| T11["置 collecting_slots -> 固定模板追问"]
    T10 -->|为空| T12{"是否冻结/挂失写操作?"}
    T12 -->|是| T13["置 awaiting_confirm + 生成幂等 request_no -> 返回二次确认摘要"]
    T12 -->|否| T14["调用中台查询/建单 -> 清空 active_task 并尝试恢复暂缓任务"]

    O2 --> P["事务性落库: chat_message + 更新 chat_session"]
    O5 --> P
    T_CANCEL --> P
    T_EXEC --> P
    T3 --> P
    T5 --> P
    T6 --> P
    T11 --> P
    T13 --> P
    T14 --> P
    P --> Z["返回 JSON { messages: [...] }"]
```

---

## 目录结构

```text
finance-data/
├── app/                                  # 银行业务中台服务（FastAPI，端口 8000）
│   ├── main.py                           # 中台入口与异常/路由装配
│   ├── config.py                         # 中台端口与同步 MySQL 连接配置
│   └── routers/                          # 账户、客户、基础配置、运营工单等业务路由
├── chat_app/                             # 智能客服对话编排后端（FastAPI，端口 8001）
│   ├── main.py                           # FastAPI 入口、lifespan（自动建表/客户端生命周期）、/health
│   ├── config.py                         # pydantic-settings 配置管理（支持同步 DB URL 自动转异步）
│   ├── constants.py                      # 状态枚举、白名单集合、确认/取消关键词、默认员工头
│   ├── clients/
│   │   └── bank_client.py                # 异步中台 HTTP 客户端（鉴权头、幂等号、异常转译）
│   ├── db/
│   │   ├── engine.py                     # SQLAlchemy AsyncEngine 与 init_db() 自动建表
│   │   ├── models.py                     # chat_session 与 chat_message ORM 模型
│   │   └── repository.py                 # 会话超时切分、历史消息查询、原子轮次落库
│   ├── llm/
│   │   ├── client.py                     # LangChain ChatOpenAI 异步调用封装
│   │   ├── prompts.py                    # NLU、S4 规则问答、闲聊引导 Prompt 模板
│   │   └── parser.py                     # JSON 清洗、单意图与白名单防幻觉校验器
│   ├── orchestrator/
│   │   ├── engine.py                     # 对话主编排器（超时判断 → 双分支分流 → 调度 → 落库）
│   │   ├── task_manager.py               # 双区任务调度器（active_task + suspended_tasks 栈）
│   │   ├── slot_templates.py             # 必填槽位映射、卡片槽位映射、固定追问与确认模板
│   │   └── handlers/                     # 各业务场景处理器
│   │       ├── account.py                # S1 账户与余额查询
│   │       ├── transaction.py            # S2 交易明细与单笔交易查询
│   │       ├── status_change.py          # S3 账户冻结/挂失（填槽 + 二次确认）
│   │       ├── faq.py                    # S4 中台基础规则实时查询与作答
│   │       ├── handoff.py                # S5 转人工创建客服工单
│   │       ├── object_card.py            # 前端 account / transaction 卡片分支处理
│   │       └── chitchat.py               # 轻量寒暄与兜底引导
│   ├── routers/
│   │   └── chat.py                       # /api/chat 与 /api/chat/history 对外路由
│   └── schemas/
│       ├── chat.py                       # 对外 API 请求/响应 Pydantic 模型（对齐前端）
│       └── nlu.py                        # 意图、槽位与任务状态数据结构
├── web/                                  # Vue 3 + Vite 前端应用（端口 5173）
│   ├── vite.config.js                    # 本地开发代理配置（/api, /health -> 8001; /bank -> 8000）
│   └── src/App.vue                       # 对话交互与右侧账户/交易卡片面板
├── tests/chat_app/                       # chat_app 单元测试套件（70 个测试用例）
├── pyproject.toml                        # Python 依赖、uv、ruff、pyright 与 pytest 配置
├── Makefile                              # 中台服务常用指令（init_db / gen / smoke / run）
├── start_all.ps1                         # Windows 一键启动三端服务脚本（8000 + 8001 + 5173）
└── SPEC.md                               # 智能客服后端技术规格说明书
```

---

## 快速开始（Quick Start）

### 1. 环境要求

- **Python**: `>= 3.12`
- **包管理器**: `uv`
- **数据库**: MySQL 8.0（需提前初始化中台业务表与测试数据）
- **Node.js**: `>= 18`（用于启动 `web/` 前端开发服务器）

### 2. 配置环境变量

在项目根目录创建 `.env` 文件，参考以下变量进行配置（`chat_app` 会自动忽略仅属于 `app/` 的环境变量）：

```env
# --- MySQL 数据库配置 ---
# 银行业务中台 (app/) 使用的独立连接参数
DB_HOST=127.0.0.1
DB_PORT=3306
DB_USER=root
DB_PASSWORD=your_mysql_password
DB_NAME=finance_data

# 智能客服后端 (chat_app/) 使用的异步连接串（若传入 mysql+pymysql:// 会自动转为 mysql+aiomysql://）
DATABASE_URL=mysql+aiomysql://root:your_mysql_password@127.0.0.1:3306/finance_data?charset=utf8mb4

# --- 服务端口与下游地址 ---
APP_PORT=8000
CHAT_APP_HOST=127.0.0.1
CHAT_APP_PORT=8001
BANK_API_BASE_URL=http://127.0.0.1:8000
BANK_API_TIMEOUT_SECONDS=10.0

# --- 大模型接入配置（OpenAI 兼容协议） ---
LLM_MODEL=qwen-plus
LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_API_KEY=your_llm_api_key
LLM_TIMEOUT_SECONDS=30.0

# --- 会话记忆与超时配置 ---
CHAT_HISTORY_WINDOW=20
CHAT_SESSION_TTL_SECONDS=3600
```

> 说明：`chat_app` 启动时会自动通过 SQLAlchemy `Base.metadata.create_all` 创建 `chat_session` 与 `chat_message` 两张客服专属表，无需手动执行建表 SQL。

### 3. 安装依赖

```bash
# 安装后端与开发依赖（创建根目录 .venv）
uv sync

# 安装前端依赖
cd web && npm install && cd ..
```

### 4. 启动服务

**方式一：Windows 一键启动三端（推荐）**

在项目根目录的 PowerShell 中执行：

```powershell
.\start_all.ps1
```

脚本将依次启动 `app`（`127.0.0.1:8000`）、`chat_app`（`127.0.0.1:8001`）与 `web`（`127.0.0.1:5173`），并在按 `Enter` 后统一清理进程树。

**方式二：分终端手动启动**

```bash
# 终端 1：启动银行业务中台 (8000)
uv run -m app.main

# 终端 2：启动智能客服后端 (8001)
uv run -m chat_app.main

# 终端 3：启动 Vue 3 前端 (5173)
cd web && npm run dev
```

启动完成后访问：
- 前端页面：`http://127.0.0.1:5173/`
- 客服健康检查：`http://127.0.0.1:8001/health`
- 中台 OpenAPI 文档：`http://127.0.0.1:8000/docs`

### 5. 运行测试与静态检查

`tests/chat_app/` 下的单元测试已通过 Mock 隔离外部 MySQL、中台 HTTP 与 LLM，可在无外网或无密钥环境下直接运行：

```bash
# 运行 chat_app 全量单元测试（70 passed）
uv run pytest tests/chat_app

# 运行 Ruff 代码规范检查
uv run ruff check chat_app tests/chat_app

# 运行 Pyright 类型检查（显式指定 .venv 解释器）
.venv\Scripts\pyright.exe --pythonpath .venv\Scripts\python.exe chat_app tests/chat_app
```

---

## 核心 API 概览

以下为 `chat_app/` 对外暴露的 HTTP 接口（前端开发模式下由 Vite 代理转发至 `127.0.0.1:8001`）：

| 方法 | 路径 | 关键参数 / 请求体 | 响应说明 | 用途 |
| --- | --- | --- | --- | --- |
| `GET` | `/health` | 无 | `{"status": "ok", "service": "chat_app"}` | 服务健康检查 |
| `POST` | `/api/chat` | `sender_id`（必填），`text` 或 `object`（二选一） | `{"messages": [{"text": "...", "object": ...}]}` | 非流式同步对话与对象卡片交互 |
| `GET` | `/api/chat/history` | Query: `sender_id`（必填） | `{"messages": [{"role": "user\|bot\|divider", ...}]}` | 拉取当前 1 小时内活跃会话历史 |

<details>
<summary>查看 <code>POST /api/chat</code> 请求与响应示例</summary>

**发送纯文本消息：**
```json
// Request
{
  "sender_id": "CUS00000001",
  "text": "查询账户余额"
}

// Response (200 OK)
{
  "messages": [
    {
      "text": "您名下共有 1 个账户：活期储蓄账户（ACC0000000001），可用余额 ￥12500.00（CNY）。"
    }
  ]
}
```

**发送对象卡片：**
```json
// Request
{
  "sender_id": "CUS00000001",
  "object": {
    "type": "account",
    "id": "ACC0000000001",
    "title": "活期储蓄账户",
    "attributes": {
      "balance_amount": "12500.00",
      "currency_code": "CNY"
    }
  }
}
```

</details>

---

## 后续规划（Roadmap）

- [ ] **接入向量库与混合 RAG**：引入轻量向量检索与业务文档切片，补充中台 `foundation` 接口未覆盖的非结构化银行规章与话术知识库。
- [ ] **Docker Compose 一键编排**：提供 `Dockerfile` 与 `docker-compose.yml`，整合 MySQL、`app`、`chat_app` 与 `web` 构建产物实现容器化交付。
- [ ] **扩展只读业务域查询**：在严格风控边界下，逐步接入中台理财持仓（`wealth`）、信贷/授信（`loans`）与还款计划（`repayments`）只读查询能力。
- [ ] **流式输出与长会话压缩**：支持 SSE 流式打字机响应及长对话摘要压缩（Summary Memory），降低长会话 Token 消耗。
