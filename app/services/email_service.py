import logging

from app.core.settings import settings

logger = logging.getLogger(__name__)


class EmailService:
    """Email delivery. No SMTP/provider is configured yet, so outside production
    the message is only logged; in production nothing is sent until a provider
    is wired into `_deliver`."""

    async def send_password_reset_otp(self, email: str, otp: str) -> None:
        subject = "Your Pebble Feet password reset code"
        body = f"Your verification code is {otp}. It expires in 5 minutes."
        await self._deliver(email, subject, body)

    async def send_order_confirmation(
        self, email: str, order_number: str, total: str, payment_method: str
    ) -> None:
        subject = f"Order {order_number} confirmed"
        body = (
            f"Thank you for shopping with Pebble Feet! Your order {order_number} "
            f"of ₹{total} ({payment_method}) is confirmed and will be packed soon."
        )
        await self._deliver(email, subject, body)

    async def send_order_status_update(
        self, email: str, order_number: str, status: str, detail: str | None = None
    ) -> None:
        subject = f"Order {order_number}: {status.replace('_', ' ')}"
        body = f"Your order {order_number} is now {status.replace('_', ' ')}."
        if detail:
            body += f" {detail}"
        await self._deliver(email, subject, body)

    async def _deliver(self, to: str, subject: str, body: str) -> None:
        if settings.environment != "production":
            logger.info("EMAIL to=%s subject=%s body=%s", to, subject, body)
            return
        logger.warning("No email provider configured; dropped email to %s", to)
