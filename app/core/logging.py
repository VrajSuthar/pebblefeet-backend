import logging
from contextvars import ContextVar

from rich.logging import RichHandler

from app.core.settings import settings

request_id_ctx: ContextVar[str] = ContextVar("request_id", default="-")

UVICORN_LOGGERS = ("uvicorn", "uvicorn.error", "uvicorn.access")


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_ctx.get()
        return True


class DropUnhandledAsgiTraceback(logging.Filter):
    # RequestLoggingMiddleware already logs the traceback; skip uvicorn's duplicate.
    def filter(self, record: logging.LogRecord) -> bool:
        return "Exception in ASGI application" not in record.getMessage()


def setup_logging() -> None:
    level = logging.DEBUG if settings.debug else logging.INFO

    handler = RichHandler(
        show_path=False,
        rich_tracebacks=True,
        markup=False,
        log_time_format="[%d %b %H:%M:%S]",
    )
    handler.addFilter(RequestIdFilter())
    handler.setFormatter(logging.Formatter("[%(request_id)s] %(message)s"))

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)

    # Route uvicorn's own logs through our handler; access logs are replaced by
    # RequestLoggingMiddleware.
    for name in UVICORN_LOGGERS:
        logger = logging.getLogger(name)
        logger.handlers = []
        logger.propagate = True
    logging.getLogger("uvicorn.access").disabled = True
    logging.getLogger("uvicorn.error").addFilter(DropUnhandledAsgiTraceback())

    logging.getLogger("asyncio").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
