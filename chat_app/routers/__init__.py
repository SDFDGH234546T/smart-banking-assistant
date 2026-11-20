"""FastAPI routers package for `chat_app`."""

from __future__ import annotations

from chat_app.routers.chat import router as chat_router

__all__ = ["chat_router"]
