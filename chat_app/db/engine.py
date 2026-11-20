"""SQLAlchemy 2.0 async engine, session factory, and schema initialization."""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from chat_app.config import get_settings
from chat_app.db.models import Base

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    """延迟创建并复用全局 AsyncEngine，避免导入阶段因缺少 DATABASE_URL 报错。"""
    global _engine
    if _engine is None:
        settings = get_settings()
        # 开启 pool_pre_ping 与 pool_recycle 防止 MySQL 长连接空闲断开（wait_timeout）
        _engine = create_async_engine(
            settings.DATABASE_URL,
            pool_pre_ping=True,
            pool_recycle=3600,
        )
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """延迟创建异步会话工厂，并禁用 expire_on_commit 以便提交后在异步上下文安全读取属性。"""
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            bind=get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
        )
    return _session_factory


async def get_db_session() -> AsyncIterator[AsyncSession]:
    """FastAPI 异步依赖生成器，发生未捕获异常时自动回滚事务。"""
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


async def init_db(engine: AsyncEngine | None = None) -> None:
    """应用启动时自动执行安全建表（CREATE TABLE IF NOT EXISTS），不触碰中台表。"""
    target_engine = engine or get_engine()
    async with target_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def dispose_engine() -> None:
    """应用关闭时释放数据库连接池并重置单例引用。"""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        _engine = None
    _session_factory = None
