import logging
import time
import uuid

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.logging import request_id_ctx

logger = logging.getLogger("app.request")

REQUEST_ID_HEADER = "x-request-id"


class RequestLoggingMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = dict(scope["headers"])
        request_id = headers.get(REQUEST_ID_HEADER.encode(), b"").decode() or uuid.uuid4().hex[:8]
        token = request_id_ctx.set(request_id)

        method = scope["method"]
        path = scope["path"]
        query = scope["query_string"].decode()
        target = f"{path}?{query}" if query else path
        client = scope["client"][0] if scope.get("client") else "-"

        status_code = 500
        start = time.perf_counter()

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                MutableHeaders(scope=message)[REQUEST_ID_HEADER] = request_id
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception:
            duration_ms = (time.perf_counter() - start) * 1000
            logger.exception("%s %s -> 500 (%.1f ms) client=%s", method, target, duration_ms, client)
            raise
        else:
            duration_ms = (time.perf_counter() - start) * 1000
            level = logging.ERROR if status_code >= 500 else logging.WARNING if status_code >= 400 else logging.INFO
            logger.log(level, "%s %s -> %d (%.1f ms) client=%s", method, target, status_code, duration_ms, client)
        finally:
            request_id_ctx.reset(token)
