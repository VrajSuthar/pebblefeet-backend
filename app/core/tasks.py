"""Periodic jobs that run inside the API process."""

import asyncio
import logging

from app.database.session import AsyncSessionLocal
from app.services.order import OrderService

logger = logging.getLogger(__name__)

SWEEP_INTERVAL_SECONDS = 300


async def expire_stale_orders_forever() -> None:
    # Safe with several workers/instances: orders are claimed with SKIP LOCKED.
    while True:
        try:
            async with AsyncSessionLocal() as db:
                cancelled = await OrderService(db).expire_stale_orders()
            if cancelled:
                logger.info("Cancelled %d unpaid order(s) and released their stock", cancelled)
        except Exception:
            logger.exception("Unpaid-order sweep failed; retrying next interval")
        await asyncio.sleep(SWEEP_INTERVAL_SECONDS)
