import asyncio
import contextlib
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.routes import auht_api_router
from app.core.exception_handlers import register_exception_handlers
from app.core.logging import setup_logging
from app.core.settings import settings
from app.core.startup_report import print_shutdown_message, print_startup_report
from app.core.tasks import expire_stale_orders_forever
from app.database.redis import redis_client
from app.database.session import engine
from app.middleware.request_logging import RequestLoggingMiddleware


@asynccontextmanager
async def lifespan(api: FastAPI):
    await print_startup_report(api)
    sweeper = asyncio.create_task(expire_stale_orders_forever())
    try:
        yield
    finally:
        sweeper.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await sweeper
        print_shutdown_message()
        await engine.dispose()
        await redis_client.aclose()


def create_app() -> FastAPI:
    setup_logging()

    app = FastAPI(
        title=settings.app_name,
        description=settings.app_description,
        version=settings.version,
        lifespan=lifespan,
    )

    app.add_middleware(RequestLoggingMiddleware)
    if settings.cors_origins:
        # Browsers refuse credentials with a "*" origin, so only allow them
        # when explicit origins are listed
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials="*" not in settings.cors_origins,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    app.include_router(auht_api_router)

    register_exception_handlers(app=app)

    return app
