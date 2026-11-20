"""Application settings loaded from environment variables and `.env`."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuration for the `chat_app` service."""

    # extra="ignore" 用于忽略 .env 中属于中台 app/ 的无关变量（如 DB_HOST、APP_PORT）
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # 服务监听配置（与中台 8000 隔离，默认运行在 8001）
    CHAT_APP_HOST: str = "127.0.0.1"
    CHAT_APP_PORT: int = Field(default=8001, ge=1, le=65535)

    # 下游银行业务中台 HTTP 地址与请求超时（秒）
    BANK_API_BASE_URL: str = "http://127.0.0.1:8000"
    BANK_API_TIMEOUT_SECONDS: float = Field(default=10.0, gt=0)

    # 异步数据库连接串（强制要求显式配置，不从 DB_* 隐式拼装）
    DATABASE_URL: str = Field(min_length=1)

    # 大模型接入配置（API Key 默认空串以便无密钥环境下运行 Mock 单测）
    LLM_MODEL: str = "qwen-plus"
    LLM_BASE_URL: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    LLM_API_KEY: str = ""
    LLM_TIMEOUT_SECONDS: float = Field(default=30.0, gt=0)

    # 多轮记忆滑动窗口大小（条数）与会话超时阈值（默认 3600 秒 = 1 小时）
    CHAT_HISTORY_WINDOW: int = Field(default=20, ge=1, le=100)
    CHAT_SESSION_TTL_SECONDS: int = Field(default=3600, ge=60)

    @field_validator("DATABASE_URL")
    @classmethod
    def _normalize_database_url(cls, value: str) -> str:
        """将同步 MySQL 驱动前缀安全转换为 SQLAlchemy 异步所需的 aiomysql 前缀。"""
        url = value.strip()
        if not url:
            raise ValueError("DATABASE_URL cannot be blank")
        if url.startswith("mysql+pymysql://"):
            return "mysql+aiomysql://" + url.removeprefix("mysql+pymysql://")
        if url.startswith("mysql://"):
            return "mysql+aiomysql://" + url.removeprefix("mysql://")
        return url

    @field_validator("BANK_API_BASE_URL", "LLM_BASE_URL")
    @classmethod
    def _strip_trailing_slash(cls, value: str) -> str:
        """统一去除 Base URL 末尾斜杠，防止后续拼接接口路径时出现双斜杠。"""
        return value.strip().rstrip("/")


# 使用 lru_cache 延迟到首次调用时实例化并复用配置对象，避免导入模块时因缺少环境变量报错
@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached application settings instance."""
    return Settings()  # type: ignore[call-arg]
