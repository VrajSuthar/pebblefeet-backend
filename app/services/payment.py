"""Razorpay payment flow.

1. POST /orders              -> order saved as PENDING, Razorpay order created
2. App opens Razorpay Checkout with the returned options
3. POST /payments/verify     -> signature checked, payment confirmed, order CONFIRMED
4. Webhook (server to server) does the same as 3 in case the app was closed
   before it could call verify; both paths are idempotent.
"""

import json
import logging
import uuid
from typing import Any

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestException, NotFoundException
from app.core.settings import settings
from app.model.order_model import Order, OrderStatus, PaymentStatus
from app.model.payment_model import Payment, TransactionStatus
from app.model.user_model import User
from app.repository.order import OrderRepository
from app.schema.order_schema import (
    OrderResponseSchema,
    RazorpayCheckoutSchema,
    RazorpayPrefillSchema,
    VerifyPaymentPayloadSchema,
)
from app.services.email_service import EmailService
from app.services.order_view import can_pay, to_order_response
from app.services.pricing import to_paise
from app.services.razorpay_client import RazorpayClient

logger = logging.getLogger(__name__)

WEBHOOK_EVENT_TTL_SECONDS = 3 * 24 * 3600


def _webhook_event_key(event_id: str) -> str:
    return f"razorpay:webhook:{event_id}"


class PaymentService:
    def __init__(self, db: AsyncSession, razorpay: RazorpayClient | None = None):
        self.repo = OrderRepository(db)
        self.razorpay = razorpay or RazorpayClient()
        self.email_service = EmailService()

    # ------------------------------ Checkout ------------------------------

    async def start_checkout(self, order: Order) -> RazorpayCheckoutSchema:
        """Razorpay Checkout options for this order. Reuses the open Razorpay
        order if there is one, so retries don't create duplicates."""
        payment = next(
            (
                p
                for p in sorted(order.payments, key=lambda p: p.created_at, reverse=True)
                if p.status == TransactionStatus.CREATED and p.amount == order.total_amount
            ),
            None,
        )
        if payment is None:
            razorpay_order = await self.razorpay.create_order(
                amount_paise=to_paise(order.total_amount),
                receipt=order.order_number,
                notes={"order_id": str(order.id), "order_number": order.order_number},
            )
            payment = Payment(
                amount=order.total_amount,
                currency=order.currency,
                razorpay_order_id=razorpay_order["id"],
                gateway_response=razorpay_order,
            )
            order.payments.append(payment)
            await self.repo.commit()

        user = order.user
        return RazorpayCheckoutSchema(
            key_id=self.razorpay.key_id,
            razorpay_order_id=payment.razorpay_order_id,
            amount=to_paise(payment.amount),
            currency=payment.currency,
            order_id=order.id,
            order_number=order.order_number,
            name=settings.app_name,
            description=f"Order {order.order_number}",
            prefill=RazorpayPrefillSchema(
                name=f"{user.first_name} {user.last_name}",
                email=user.email,
                contact=user.phone_number,
            ),
        )

    async def retry_checkout(self, user: User, order_id: uuid.UUID) -> RazorpayCheckoutSchema:
        order = await self.repo.get_order(order_id, user_id=user.id)
        if order is None:
            raise NotFoundException("Order not found")
        if not can_pay(order):
            raise BadRequestException("This order does not need a payment")
        return await self.start_checkout(order)

    # ------------------------------ Verify (from the app) ------------------------------

    async def verify(
        self, user: User, payload: VerifyPaymentPayloadSchema
    ) -> OrderResponseSchema:
        payment = await self.repo.get_payment_by_razorpay_order(payload.razorpay_order_id)
        if payment is None:
            raise NotFoundException("Payment not found")
        order = await self.repo.get_order(payment.order_id, user_id=user.id, for_update=True)
        if order is None:
            raise NotFoundException("Payment not found")

        if not self.razorpay.verify_payment_signature(
            payload.razorpay_order_id, payload.razorpay_payment_id, payload.razorpay_signature
        ):
            raise BadRequestException(
                "Payment verification failed", code="PAYMENT_SIGNATURE_INVALID"
            )

        # The signature proves Razorpay issued this payment id; fetching it
        # tells us whether money was actually taken.
        details = await self.razorpay.fetch_payment(payload.razorpay_payment_id)
        if details.get("status") == "authorized":
            details = await self.razorpay.capture_payment(
                payload.razorpay_payment_id, to_paise(payment.amount)
            )
        if details.get("status") != "captured":
            raise BadRequestException(
                "Payment is not complete yet. If money was deducted it will be "
                "confirmed automatically in a few minutes.",
                code="PAYMENT_PENDING",
            )

        await self._settle_captured(
            order, payment.id, details, signature=payload.razorpay_signature
        )
        return to_order_response(order)

    # ------------------------------ Webhook (from Razorpay) ------------------------------

    async def handle_webhook(
        self, body: bytes, signature: str, event_id: str | None, redis: Redis
    ) -> None:
        if not self.razorpay.verify_webhook_signature(body, signature):
            raise BadRequestException("Invalid webhook signature", code="WEBHOOK_SIGNATURE_INVALID")

        # Razorpay retries deliveries; skip ones we already processed.
        if event_id and await redis.exists(_webhook_event_key(event_id)):
            return

        event = json.loads(body)
        name = event.get("event")
        payload = event.get("payload", {})
        if name in ("payment.captured", "order.paid"):
            await self._on_captured(payload["payment"]["entity"])
        elif name == "payment.failed":
            await self._on_failed(payload["payment"]["entity"])
        elif name == "refund.processed":
            await self._on_refunded(payload["refund"]["entity"])
        else:
            logger.info("Ignoring Razorpay webhook event %s", name)

        if event_id:
            await redis.set(_webhook_event_key(event_id), "1", ex=WEBHOOK_EVENT_TTL_SECONDS)

    async def _locked_order_for(self, razorpay_order_id: str) -> tuple[Order, Payment] | None:
        payment = await self.repo.get_payment_by_razorpay_order(razorpay_order_id)
        if payment is None:
            logger.warning("Webhook for unknown Razorpay order %s", razorpay_order_id)
            return None
        order = await self.repo.get_order(payment.order_id, for_update=True)
        if order is None:
            return None
        # Re-read the payment through the locked order so its status is current
        return order, next(p for p in order.payments if p.id == payment.id)

    async def _on_captured(self, entity: dict[str, Any]) -> None:
        found = await self._locked_order_for(entity.get("order_id", ""))
        if found is None:
            return
        order, payment = found
        if entity.get("amount") != to_paise(payment.amount):
            logger.error(
                "Amount mismatch on %s: got %s paise, expected %s",
                payment.razorpay_order_id, entity.get("amount"), to_paise(payment.amount),
            )
            return
        await self._settle_captured(order, payment.id, entity)

    async def _on_failed(self, entity: dict[str, Any]) -> None:
        found = await self._locked_order_for(entity.get("order_id", ""))
        if found is None:
            return
        order, payment = found
        if payment.status in (TransactionStatus.CAPTURED, TransactionStatus.REFUNDED):
            # A later attempt on the same Razorpay order already succeeded
            return

        payment.status = TransactionStatus.FAILED
        payment.failure_reason = (entity.get("error_description") or "Payment failed")[:255]
        payment.method = entity.get("method")
        payment.gateway_response = entity
        if order.payment_status == PaymentStatus.PENDING:
            # Order stays PENDING so the customer can try again until it expires
            order.payment_status = PaymentStatus.FAILED
        await self.repo.commit()

    async def _on_refunded(self, entity: dict[str, Any]) -> None:
        payment = await self.repo.get_payment_by_razorpay_payment(entity.get("payment_id", ""))
        if payment is None:
            return
        order = await self.repo.get_order(payment.order_id, for_update=True)
        if order is None:
            return
        payment = next(p for p in order.payments if p.id == payment.id)
        if payment.status == TransactionStatus.REFUNDED:
            return

        # Refunds started from the Razorpay dashboard land here too
        payment.razorpay_refund_id = entity.get("id")
        if entity.get("amount", 0) >= to_paise(payment.amount):
            payment.status = TransactionStatus.REFUNDED
            order.payment_status = PaymentStatus.REFUNDED
        else:
            order.payment_status = PaymentStatus.PARTIALLY_REFUNDED
        await self.repo.commit()

    # ------------------------------ Settling ------------------------------

    async def _settle_captured(
        self,
        order: Order,
        payment_id: uuid.UUID,
        details: dict[str, Any],
        signature: str | None = None,
    ) -> None:
        """Record a captured payment. `order` must be locked FOR UPDATE.
        Safe to call twice (verify + webhook)."""
        payment = next(p for p in order.payments if p.id == payment_id)
        if payment.status in (TransactionStatus.CAPTURED, TransactionStatus.REFUNDED):
            return

        payment.status = TransactionStatus.CAPTURED
        payment.razorpay_payment_id = details.get("id")
        payment.razorpay_signature = signature or payment.razorpay_signature
        payment.method = details.get("method")
        payment.failure_reason = None
        payment.gateway_response = details

        if order.status == OrderStatus.CANCELLED or order.payment_status == PaymentStatus.PAID:
            # Paid after the order expired or was cancelled, or paid twice:
            # give the money back straight away.
            reason = (
                "Order was cancelled before the payment completed"
                if order.status == OrderStatus.CANCELLED
                else "Duplicate payment"
            )
            await self._refund(order, payment, reason, settles_order=order.status == OrderStatus.CANCELLED)
            self.repo.add_history(order, order.status, note=f"Payment refunded: {reason}")
            await self.repo.commit()
            await self.email_service.send_order_status_update(
                order.user.email, order.order_number, "refunded",
                f"We received a payment for this order and refunded it ({reason.lower()}).",
            )
            return

        order.payment_status = PaymentStatus.PAID
        if order.status == OrderStatus.PENDING:
            order.status = OrderStatus.CONFIRMED
            self.repo.add_history(
                order, OrderStatus.CONFIRMED, note=f"Payment received ({payment.method or 'online'})"
            )
        await self.repo.commit()
        await self.email_service.send_order_confirmation(
            order.user.email, order.order_number, str(order.total_amount), "paid online"
        )

    async def _refund(
        self, order: Order, payment: Payment, reason: str, settles_order: bool
    ) -> None:
        if payment.razorpay_payment_id is None:
            return
        refund = await self.razorpay.refund_payment(
            payment.razorpay_payment_id,
            to_paise(payment.amount),
            notes={"order_number": order.order_number, "reason": reason[:200]},
        )
        payment.status = TransactionStatus.REFUNDED
        payment.razorpay_refund_id = refund.get("id")
        if settles_order:
            order.payment_status = PaymentStatus.REFUNDED

    async def refund_order(self, order: Order, reason: str) -> bool:
        """Refund the captured online payment of a locked order. Not committed;
        the caller commits together with its own changes. Returns whether a
        refund was issued."""
        captured = [p for p in order.payments if p.status == TransactionStatus.CAPTURED]
        for payment in captured:
            await self._refund(order, payment, reason, settles_order=True)
        return bool(captured)

    async def reconcile(self, order: Order) -> bool:
        """Ask Razorpay whether a pending order was paid after all (a missed
        webhook). Returns True if it was, and records the payment."""
        for payment in order.payments:
            if payment.status not in (TransactionStatus.CREATED, TransactionStatus.FAILED):
                continue
            razorpay_order = await self.razorpay.fetch_order(payment.razorpay_order_id)
            if razorpay_order.get("status") != "paid":
                continue
            for attempt in await self.razorpay.fetch_order_payments(payment.razorpay_order_id):
                if attempt.get("status") == "authorized":
                    attempt = await self.razorpay.capture_payment(
                        attempt["id"], to_paise(payment.amount)
                    )
                if attempt.get("status") == "captured":
                    await self._settle_captured(order, payment.id, attempt)
                    return True
        return False
