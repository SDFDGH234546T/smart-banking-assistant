"""FastAPI application entry point, lifespan wiring, and global error handling."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from chat_app.clients.bank_client import BankClient
from chat_app.config import get_settings
from chat_app.db.engine import dispose_engine, init_db
from chat_app.llm.client import LLMClient
from chat_app.orchestrator.engine import ChatOrchestrator
from chat_app.routers.chat import router as chat_router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """应用生命周期管理：启动时自动建表并初始化共享异步客户端，关闭时优雅释放资源。"""
    settings = get_settings()
    await init_db()

    # 禁用 trust_env 防止系统代理环境变量劫持本地 127.0.0.1:8000 中台请求并返回代理 HTML 错误页
    http_client = httpx.AsyncClient(trust_env=False)
    bank_client = BankClient(
        http_client,
        base_url=settings.BANK_API_BASE_URL,
        timeout=settings.BANK_API_TIMEOUT_SECONDS,
    )
    llm_client = LLMClient(
        model=settings.LLM_MODEL,
        base_url=settings.LLM_BASE_URL,
        api_key=settings.LLM_API_KEY,
        timeout=settings.LLM_TIMEOUT_SECONDS,
    )
    app.state.http_client = http_client
    app.state.orchestrator = ChatOrchestrator(
        bank_client=bank_client,
        llm_client=llm_client,
        settings=settings,
    )
    try:
        yield
    finally:
        await http_client.aclose()
        await dispose_engine()


def create_app() -> FastAPI:
    """构造并返回配置完成的 FastAPI 实例。"""
    app = FastAPI(
        title="智能银行客服后端 (chat_app)",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.include_router(chat_router)

    @app.get("/health", summary="服务健康检查")
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": "chat_app"}

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(
        request: Request, exc: Exception
    ) -> JSONResponse:
        # 统一返回 {"detail": ...} 契约，避免向前端暴露原始堆栈或英文异常
        logger.exception("Unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=500,
            content={"detail": "智能客服服务暂时开小差了，请稍后重试。"},
        )

    return app


app = create_app()


def main() -> None:
    """使用 uvicorn 启动客服后端服务（默认 127.0.0.1:8001）。"""
    settings = get_settings()
    uvicorn.run(
        "chat_app.main:app",
        host=settings.CHAT_APP_HOST,
        port=settings.CHAT_APP_PORT,
        reload=False,
    )


if __name__ == "__main__":
    main()
