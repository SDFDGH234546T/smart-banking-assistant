# 阶段 1 总结与设计复盘（环境核查、配置与数据模型层）

> 本文档记录 `chat_app` 阶段 1（`T1.1` ~ `T1.4`）的**具体产出**与**核心设计原因（Why）**，便于后续阶段开发与学习复盘。

---

## 1. 阶段目标与整体定位

阶段 1 为智能银行客服后端 `chat_app` 搭建了可测试、全异步的底层基础设施，完成以下四层闭环：

```text
T1.1 真实库表枚举与确定性常量 (constants.py)
   ↓
T1.2 环境变量配置与异步驱动兼容 (config.py)
   ↓
T1.3 SQLAlchemy 2.0 异步引擎与双表 ORM (db/engine.py, db/models.py)
   ↓
T1.4 会话生命周期与原子轮次持久化 (db/repository.py)
```

---

## 2. 各子任务做了什么 & 为什么要这么做

| 子任务 | 核心产出文件 | 具体做了什么 | 为什么要这么做（设计原因） |
| --- | --- | --- | --- |
| **T1.1** | [constants.py](file:///d:/0708/尚硅谷大模型项目实战之掌柜小二实战/finance-data/chat_app/constants.py)<br>[`__init__.py`](file:///d:/0708/尚硅谷大模型项目实战之掌柜小二实战/finance-data/chat_app/__init__.py) | 只读核查 MySQL `bank_account`、`support_ticket`、`dim_channel` 字段约束并对照中台 `app/`，固化渠道编码、账户状态/写操作白名单、工单默认值、确认/取消关键词及 NLU 意图与任务白名单。 | 1. **杜绝臆测枚举**：MySQL 中 `account_status` 与 `ticket_type` 为 `varchar(64)` 而非强 `ENUM`，查库+查代码才能区分全量展示状态（`normal`/`active`/`frozen`/`lost`/`closed`）与 S3 写操作白名单（仅 `frozen`/`lost`），防止误关户。<br>2. **确定性优先**：确认/取消词与任务白名单由代码强校验，防止大模型幻觉越权。 |
| **T1.2** | [config.py](file:///d:/0708/尚硅谷大模型项目实战之掌柜小二实战/finance-data/chat_app/config.py)<br>[test_config.py](file:///d:/0708/尚硅谷大模型项目实战之掌柜小二实战/finance-data/tests/chat_app/test_config.py) | 基于 `pydantic-settings` 定义 `Settings` 与 `@lru_cache` 封装的 `get_settings()`，加载 `8001` 端口、中台地址、LLM 参数、窗口大小、会话 TTL 与必填 `DATABASE_URL`。 | 1. **忽略中台变量**：`.env` 含 `DB_HOST`、`APP_PORT` 等中台字段，设置 `extra="ignore"` 避免解析报错。<br>2. **异步前缀兼容**：将 `mysql://` / `mysql+pymysql://` 自动转为 `mysql+aiomysql://`，保证全链路异步驱动一致。<br>3. **延迟实例化**：通过 `get_settings()` 延迟读取，避免无环境变量时一导入模块就报错，便于单测隔离。 |
| **T1.3** | [models.py](file:///d:/0708/尚硅谷大模型项目实战之掌柜小二实战/finance-data/chat_app/db/models.py)<br>[engine.py](file:///d:/0708/尚硅谷大模型项目实战之掌柜小二实战/finance-data/chat_app/db/engine.py)<br>[test_models.py](file:///d:/0708/尚硅谷大模型项目实战之掌柜小二实战/finance-data/tests/chat_app/test_models.py) | 定义 `ChatSession`（`chat_session`）与 `ChatMessage`（`chat_message`）及联合索引；实现延迟初始化的 `get_engine()`、`get_session_factory()`、`get_db_session()`、`init_db()` 与 `dispose_engine()`。 | 1. **表物理隔离**：新增 `chat_` 前缀两张表，不触碰任何中台业务表。<br>2. **本地时区对齐**：`local_now()` 沿用中台 `Asia/Shanghai` 无时区时间，避免与 MySQL `DATETIME` 对比出现 8 小时时差导致 1 小时超时误判。<br>3. **异步连接稳健性**：`pool_pre_ping=True` 与 `pool_recycle=3600` 防止 MySQL 长连接断开；`expire_on_commit=False` 防止异步提交后读取属性报错；`default_task_state` 工厂函数避免多行共享可变字典。 |
| **T1.4** | [repository.py](file:///d:/0708/尚硅谷大模型项目实战之掌柜小二实战/finance-data/chat_app/db/repository.py)<br>[test_repository.py](file:///d:/0708/尚硅谷大模型项目实战之掌柜小二实战/finance-data/tests/chat_app/test_repository.py) | 实现 `is_session_expired`、`get_active_session_if_valid`、`get_or_create_active_session`、`get_recent_messages` 与 `save_turn`。 | 1. **只读与写入分离**：`get_active_session_if_valid` 仅只读判超时，保证 `GET /api/chat/history` 无写入副作用；状态切换统一收口在 `get_or_create_active_session`。<br>2. **并发兜底**：若因竞态出现多条 `active` 会话，统一将旧会话置 `expired`。<br>3. **高效正序窗口**：`get_recent_messages` 先按 `id DESC` 截断最新 `N` 条再反转正序，兼顾性能与对话顺序。<br>4. **事务原子落库**：`save_turn` 在同一事务内写入 `user`/`bot` 消息、递增 `turn_count` 并更新 `task_state_json`，避免消息与状态不一致。 |

---

## 3. 阶段 1 验证与沉淀汇总

- **单元测试**：
  - `tests/chat_app/test_config.py`：6 passed
  - `tests/chat_app/test_models.py`：6 passed
  - `tests/chat_app/test_repository.py`：5 passed
- **静态检查**：`ruff check` 与 `pyright --pythonpath .venv\Scripts\python.exe` 均 0 errors、0 warnings。
- **避坑沉淀**（已记录至 [LESSONS.md](file:///d:/0708/尚硅谷大模型项目实战之掌柜小二实战/finance-data/LESSONS.md)）：
  - Pyright 需显式指定 `--pythonpath .venv\Scripts\python.exe`。
  - Windows 沙盒环境运行含 `asyncio` / `@pytest.mark.anyio` 的异步单测需在沙盒外执行。
