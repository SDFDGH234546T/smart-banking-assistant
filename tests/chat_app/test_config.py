"""Unit tests for `chat_app.config`."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from chat_app.config import Settings, get_settings


def test_settings_requires_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("DB_HOST", "127.0.0.1")
    monkeypatch.setenv("DB_PORT", "3306")

    with pytest.raises(ValidationError):
        Settings(_env_file=None)  # type: ignore[call-arg]


@pytest.mark.parametrize(
    ("raw_url", "expected_url"),
    [
        (
            "mysql://root:123456@127.0.0.1:3306/atguigu",
            "mysql+aiomysql://root:123456@127.0.0.1:3306/atguigu",
        ),
        (
            "mysql+pymysql://root:123456@127.0.0.1:3306/atguigu?charset=utf8mb4",
            "mysql+aiomysql://root:123456@127.0.0.1:3306/atguigu?charset=utf8mb4",
        ),
        (
            "mysql+aiomysql://root:123456@127.0.0.1:3306/atguigu",
            "mysql+aiomysql://root:123456@127.0.0.1:3306/atguigu",
        ),
    ],
)
def test_database_url_prefix_normalization(
    monkeypatch: pytest.MonkeyPatch, raw_url: str, expected_url: str
) -> None:
    monkeypatch.setenv("DATABASE_URL", raw_url)
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    assert settings.DATABASE_URL == expected_url


def test_settings_defaults_and_ignores_extra_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "mysql+aiomysql://root:pass@localhost:3306/db")
    monkeypatch.setenv("APP_PORT", "8000")
    monkeypatch.setenv("DB_NAME", "atguigu")
    monkeypatch.setenv("BANK_API_BASE_URL", "http://127.0.0.1:8000/")

    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    assert settings.CHAT_APP_HOST == "127.0.0.1"
    assert settings.CHAT_APP_PORT == 8001
    assert settings.BANK_API_BASE_URL == "http://127.0.0.1:8000"
    assert settings.BANK_API_TIMEOUT_SECONDS == 10.0
    assert settings.LLM_MODEL == "qwen-plus"
    assert settings.LLM_BASE_URL == "https://dashscope.aliyuncs.com/compatible-mode/v1"
    assert settings.LLM_API_KEY == ""
    assert settings.LLM_TIMEOUT_SECONDS == 30.0
    assert settings.CHAT_HISTORY_WINDOW == 20
    assert settings.CHAT_SESSION_TTL_SECONDS == 3600


def test_get_settings_cache_and_reload(monkeypatch: pytest.MonkeyPatch) -> None:
    get_settings.cache_clear()
    monkeypatch.setenv("DATABASE_URL", "mysql+aiomysql://u:p@localhost:3306/db1")
    monkeypatch.setenv("CHAT_APP_PORT", "8002")

    first = get_settings()
    second = get_settings()
    assert first is second
    assert first.CHAT_APP_PORT == 8002

    monkeypatch.setenv("CHAT_APP_PORT", "8003")
    get_settings.cache_clear()
    third = get_settings()
    assert third is not first
    assert third.CHAT_APP_PORT == 8003
    get_settings.cache_clear()
