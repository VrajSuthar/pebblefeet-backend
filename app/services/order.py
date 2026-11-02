import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    AppException,
    BadRequestException,
    NotFoundException,
    PaymentGatewayException,
    ServiceUnavailableException,
)
from app.core.settings import settings
from app.model.coupon_model import Coupon
from app.model.order_model import (
    Order,
    OrderItem,
    OrderStatus,
    OrderStatusHistory,
    PaymentMethod,
    PaymentStatus,
)
from app.model.payment_model import TransactionStatus
from app.model.user_model import User, UserAddress
from app.repository.cart import CartRepository
from app.repository.order import OrderRepository
from app.schema.common_schema import PageSchema
from app.schema.order_schema import (
    AdminOrderListItemSchema,
    AdminOrderQuerySchema,
    AdminOrderResponseSchema,
    AdminOrderStatusPayloadSchema,
    CancelOrderPayloadSchema,
    CheckoutLineSchema,
    CheckoutPreviewPayloadSchema,
    CheckoutPreviewSchema,
    OrderListItemSchema,
    OrderQuerySchema,
    OrderResponseSchema,
    PlaceOrderPayloadSchema,
    PlaceOrderResponseSchema,
    ReturnRequestPayloadSchema,
)
from app.services.cart import availability_issue, variant_image_url
from app.services.coupon import CouponService
from app.services.email_service import EmailService
from app.services.order_view import (
    can_cancel,
    can_return,
    to_admin_order_list_item,
    to_admin_order_response,
    to_order_list_item,
    to_order_response,
)
from app.services.payment import PaymentService
from app.services.pricing import ZERO, Line, PriceBreakdown, money, price_order
from app.services.razorpay_client import RazorpayClient

logger = logging.getLogger(__name__)

IST = ZoneInfo("Asia/Kolkata")
# No 0/O or 1/I so order numbers are easy to read out over the phone
ORDER_NUMBER_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
SWEEP_BATCH_LIMIT = 100

# What the store may move an order to from each status. Moving PENDING to
# CONFIRMED is left to the payment flow, never done by hand.
ADMIN_TRANSITIONS: dict[OrderStatus, set[OrderStatus]] = {
    OrderStatus.PENDING: {OrderStatus.CANCELLED},
    OrderStatus.CONFIRMED: {OrderStatus.PROCESSING, OrderStatus.CANCELLED},
    OrderStatus.PROCESSING: {OrderStatus.SHIPPED, OrderStatus.CANCELLED},
    OrderStatus.SHIPPED: {OrderStatus.OUT_FOR_DELIVERY, OrderStatus.DELIVERED},
    OrderStatus.OUT_FOR_DELIVERY: {OrderStatus.DELIVERED},
    OrderStatus.DELIVERED: {OrderStatus.RETURNED},
    # Back to DELIVERED means the return request was rejected
    OrderStatus.RETURN_REQUESTED: {OrderStatus.RETURNED, OrderStatus.DELIVERED},
    OrderStatus.CANCELLED: set(),
    OrderStatus.RETURNED: set(),
}

# Customer gets an email when the order reaches one of these
NOTIFY_STATUSES = {
    OrderStatus.SHIPPED,
    OrderStatus.OUT_FOR_DELIVERY,
    OrderStatus.DELIVERED,
    OrderStatus.RETURNED,
}


def _new_order_number() -> str:
    suffix = "".join(secrets.choice(ORDER_NUMBER_ALPHABET) for _ in range(6))
    return f"PF-{datetime.now(IST):%Y%m%d}-{suffix}"


def _address_snapshot(address: UserAddress) -> dict[str, str | None]:
    return {
        "recipient_name": address.recipient_name,
        "phone_number": address.phone_number,
        "address_line1": address.address_line1,
        "address_line2": address.address_line2,
        "landmark": address.landmark,
        "city": address.city,
        "state": address.state,
        "postal_code": address.postal_code,
        "country": address.country,
        "address_type": address.address_type.value,
    }


class OrderService:
    def __init__(self, db: AsyncSession, razorpay: RazorpayClient | None = None):
        self.repo = OrderRepository(db)
        self.cart_repo = CartRepository(db)
        self.coupon_service = CouponService(db)
        self.payment_service = PaymentService(db, razorpay=razorpay)
        self.email_service = EmailService()

    # ------------------------------ Helpers ------------------------------

    async def _get_or_404(
        self, order_id: uuid.UUID, user_id: uuid.UUID | None = None, for_update: bool = False
    ) -> Order:
        order = await self.repo.get_order(order_id, user_id=user_id, for_update=for_update)
        if order is None:
            raise NotFoundException("Order not found")
        return order

    async def _price(
        self, user: User, lines: list[Line], coupon_code: str | None, lock_coupon: bool
    ) -> tuple[PriceBreakdown, Coupon | None]:
        coupon = None
        if coupon_code:
            subtotal = money(sum((line.total for line in lines), ZERO))
            coupon = await self.coupon_service.validate(
                coupon_code, user.id, subtotal, for_update=lock_coupon
            )
        return price_order(lines, coupon), coupon

    @staticmethod
    def _cod_available(total: Decimal) -> bool:
        return settings.cod_enabled and total <= settings.cod_max_order_amount

    # ------------------------------ Checkout ------------------------------

    async def preview(
        self, user: User, payload: CheckoutPreviewPayloadSchema
    ) -> CheckoutPreviewSchema:
        """Totals for the checkout screen; nothing is reserved yet."""
        items = await self.cart_repo.list_items(user.id)
        if not items:
            raise BadRequestException("Your cart is empty", code="CART_EMPTY")
        for item in items:
            issue = availability_issue(item.variant, item.quantity)
            if issue:
                raise BadRequestException(
                    f"{item.variant.product.name} ({item.variant.name}): {issue}",
                    code="CART_ITEM_UNAVAILABLE",
                )

        lines = [Line(i.variant.price, i.quantity, i.variant.product.gst_rate) for i in items]
        breakdown, coupon = await self._price(user, lines, payload.coupon_code, lock_coupon=False)
        return CheckoutPreviewSchema(
            items=[
                CheckoutLineSchema(
                    variant_id=i.variant_id,
                    product_name=i.variant.product.name,
                    variant_name=i.variant.name,
                    image_url=variant_image_url(i.variant),
                    quantity=i.quantity,
                    unit_price=i.variant.price,
                    line_total=line.total,
                )
                for i, line in zip(items, breakdown.lines)
            ],
            coupon_code=coupon.code if coupon else None,
            subtotal=breakdown.subtotal,
            discount_amount=breakdown.discount_amount,
            shipping_fee=breakdown.shipping_fee,
            tax_amount=breakdown.tax_amount,
            total_amount=breakdown.total_amount,
            cod_available=self._cod_available(breakdown.total_amount),
        )

    async def place_order(
        self, user: User, payload: PlaceOrderPayloadSchema
    ) -> PlaceOrderResponseSchema:
        """Turns the cart into an order in one transaction: stock is reserved,
        the coupon is used up and the cart is emptied, or nothing happens."""
        if payload.payment_method == PaymentMethod.RAZORPAY and not settings.razorpay_enabled:
            raise ServiceUnavailableException("Online payments are not available right now")
        if payload.payment_method == PaymentMethod.COD and not settings.cod_enabled:
            raise BadRequestException("Cash on delivery is not available")

        address = await self.repo.get_user_address(user.id, payload.address_id)
        if address is None:
            raise NotFoundException("Address not found")

        cart_items = await self.cart_repo.list_items(user.id)
        if not cart_items:
            raise BadRequestException("Your cart is empty", code="CART_EMPTY")

        variants = {
            v.id: v for v in await self.repo.lock_variants([i.variant_id for i in cart_items])
        }
        for item in cart_items:
            variant = variants[item.variant_id]
            issue = availability_issue(variant, item.quantity)
            if issue:
                raise BadRequestException(
                    f"{variant.product.name} ({variant.name}): {issue}",
                    code="CART_ITEM_UNAVAILABLE",
                )

        lines = [
            Line(variants[i.variant_id].price, i.quantity, variants[i.variant_id].product.gst_rate)
            for i in cart_items
        ]
        breakdown, coupon = await self._price(user, lines, payload.coupon_code, lock_coupon=True)

        if payload.payment_method == PaymentMethod.COD and not self._cod_available(
            breakdown.total_amount
        ):
            raise BadRequestException(
                f"Cash on delivery is available for orders up to ₹{settings.cod_max_order_amount}"
            )

        is_cod = payload.payment_method == PaymentMethod.COD
        status = OrderStatus.CONFIRMED if is_cod else OrderStatus.PENDING

        order_number = _new_order_number()
        while await self.repo.order_number_exists(order_number):
            order_number = _new_order_number()

        order = Order(
            order_number=order_number,
            user_id=user.id,
            coupon_id=coupon.id if coupon else None,
            status=status,
            payment_status=PaymentStatus.PENDING,
            payment_method=payload.payment_method,
            subtotal=breakdown.subtotal,
            discount_amount=breakdown.discount_amount,
            shipping_fee=breakdown.shipping_fee,
            tax_amount=breakdown.tax_amount,
            total_amount=breakdown.total_amount,
            shipping_address=_address_snapshot(address),
            customer_note=payload.customer_note,
            items=[],
            status_history=[
                OrderStatusHistory(
                    status=status,
                    note="Cash on delivery order placed" if is_cod else "Awaiting payment",
                    changed_by_id=user.id,
                )
            ],
            payments=[],
        )
        for item, line in zip(cart_items, breakdown.lines):
            variant = variants[item.variant_id]
            order.items.append(
                OrderItem(
                    variant_id=variant.id,
                    product_name=variant.product.name,
                    sku=variant.sku,
                    variant_name=variant.name,
                    image_url=variant_image_url(variant),
                    quantity=item.quantity,
                    unit_price=variant.price,
                    total_price=line.total,
                    hsn_code=variant.product.hsn_code,
                    gst_rate=variant.product.gst_rate,
                )
            )
            # Reserved now; given back if the order is cancelled or expires
            variant.stock -= item.quantity

        if coupon is not None:
            await self.coupon_service.redeem(coupon)
        await self.cart_repo.clear(user.id, commit=False)
        self.repo.add(order)
        await self.repo.commit()

        order = await self._get_or_404(order.id)
        if is_cod:
            await self.email_service.send_order_confirmation(
                order.user.email, order.order_number, str(order.total_amount), "cash on delivery"
            )
            return PlaceOrderResponseSchema(order=to_order_response(order), payment=None)

        try:
            checkout = await self.payment_service.start_checkout(order)
        except (PaymentGatewayException, ServiceUnavailableException) as exc:
            # The order and its stock reservation are kept; the app retries
            # with POST /orders/{id}/pay until the order expires.
            return PlaceOrderResponseSchema(
                order=to_order_response(order), payment=None, payment_error=exc.message
            )
        return PlaceOrderResponseSchema(order=to_order_response(order), payment=checkout)

    # ------------------------------ Customer ------------------------------

    async def list_orders(
        self, user: User, query: OrderQuerySchema
    ) -> PageSchema[OrderListItemSchema]:
        orders, total = await self.repo.list_orders(user.id, query)
        return PageSchema[OrderListItemSchema](
            items=[to_order_list_item(o) for o in orders],
            total=total,
            page=query.page,
            page_size=query.page_size,
        )

    async def get_order(self, user: User, order_id: uuid.UUID) -> OrderResponseSchema:
        return to_order_response(await self._get_or_404(order_id, user_id=user.id))

    async def cancel_order(
        self, user: User, order_id: uuid.UUID, payload: CancelOrderPayloadSchema
    ) -> OrderResponseSchema:
        order = await self._get_or_404(order_id, user_id=user.id, for_update=True)
        if not can_cancel(order):
            raise BadRequestException(
                f"This order can no longer be cancelled (it is {order.status.value.replace('_', ' ')})"
            )
        await self._cancel(order, payload.reason or "Cancelled by customer", changed_by_id=user.id)
        return to_order_response(order)

    async def request_return(
        self, user: User, order_id: uuid.UUID, payload: ReturnRequestPayloadSchema
    ) -> OrderResponseSchema:
        order = await self._get_or_404(order_id, user_id=user.id, for_update=True)
        if not can_return(order):
            raise BadRequestException(
                f"Returns are accepted within {settings.return_window_days} days of delivery"
            )
        order.status = OrderStatus.RETURN_REQUESTED
        self.repo.add_history(order, OrderStatus.RETURN_REQUESTED, payload.reason, user.id)
        await self.repo.commit()
        return to_order_response(order)

    # ------------------------------ Shared transitions ------------------------------

    async def _cancel(
        self, order: Order, reason: str, changed_by_id: uuid.UUID | None
    ) -> None:
        """Cancel a locked order: refund, restock, give the coupon back."""
        refunded = False
        if order.payment_status == PaymentStatus.PAID and order.payment_method == PaymentMethod.RAZORPAY:
            # Refund first: if Razorpay refuses, nothing below is committed
            refunded = await self.payment_service.refund_order(order, reason)

        await self.repo.restock(order)
        if order.coupon_id is not None:
            await self.coupon_service.release(order.coupon_id)
        for payment in order.payments:
            if payment.status == TransactionStatus.CREATED:
                # So a stale Checkout can't be reused for a cancelled order
                payment.status = TransactionStatus.FAILED
                payment.failure_reason = "Order cancelled"

        order.status = OrderStatus.CANCELLED
        order.cancelled_at = datetime.now(timezone.utc)
        order.cancellation_reason = reason
        self.repo.add_history(order, OrderStatus.CANCELLED, reason, changed_by_id)
        await self.repo.commit()

        detail = "Your refund has been started and reaches you in 5-7 working days." if refunded else None
        await self.email_service.send_order_status_update(
            order.user.email, order.order_number, OrderStatus.CANCELLED.value, detail
        )

    # ------------------------------ Admin ------------------------------

    async def admin_list_orders(
        self, query: AdminOrderQuerySchema
    ) -> PageSchema[AdminOrderListItemSchema]:
        orders, total = await self.repo.admin_list_orders(query)
        return PageSchema[AdminOrderListItemSchema](
            items=[to_admin_order_list_item(o) for o in orders],
            total=total,
            page=query.page,
            page_size=query.page_size,
        )

    async def admin_get_order(self, order_id: uuid.UUID) -> AdminOrderResponseSchema:
        return to_admin_order_response(await self._get_or_404(order_id))

    async def admin_update_status(
        self, admin: User, order_id: uuid.UUID, payload: AdminOrderStatusPayloadSchema
    ) -> AdminOrderResponseSchema:
        order = await self._get_or_404(order_id, for_update=True)
        old, new = order.status, payload.status

        if new not in ADMIN_TRANSITIONS[old]:
            allowed = ", ".join(sorted(s.value for s in ADMIN_TRANSITIONS[old])) or "none"
            raise BadRequestException(
                f"Cannot move an order from {old.value} to {new.value} (allowed: {allowed})",
                code="INVALID_STATUS_TRANSITION",
            )

        if new == OrderStatus.CANCELLED:
            await self._cancel(order, payload.note or "Cancelled by the store", admin.id)
            return to_admin_order_response(order)

        if payload.courier_name:
            order.courier_name = payload.courier_name
        if payload.tracking_number:
            order.tracking_number = payload.tracking_number
        now = datetime.now(timezone.utc)
        note, detail = payload.note, payload.note

        if new == OrderStatus.SHIPPED:
            if not (order.courier_name and order.tracking_number):
                raise BadRequestException("Courier name and tracking number are required to ship")
            order.shipped_at = now
            detail = f"Courier: {order.courier_name}, tracking number: {order.tracking_number}."
        elif new == OrderStatus.DELIVERED:
            if old != OrderStatus.RETURN_REQUESTED:
                order.delivered_at = now
            if order.payment_method == PaymentMethod.COD:
                # Cash was collected by the courier
                order.payment_status = PaymentStatus.PAID
        elif new == OrderStatus.RETURNED:
            await self.repo.restock(order)
            if order.payment_method == PaymentMethod.RAZORPAY and order.payment_status == PaymentStatus.PAID:
                await self.payment_service.refund_order(order, note or "Order returned")
                detail = "Your refund has been started and reaches you in 5-7 working days."
            else:
                # COD money has to be sent back by hand (UPI / bank transfer)
                note = f"{note or 'Returned'} (cash on delivery: refund the customer manually)"

        order.status = new
        self.repo.add_history(order, new, note, admin.id)
        await self.repo.commit()

        if new in NOTIFY_STATUSES:
            await self.email_service.send_order_status_update(
                order.user.email, order.order_number, new.value, detail
            )
        return to_admin_order_response(order)

    # ------------------------------ Background ------------------------------

    async def expire_stale_orders(self) -> int:
        """Cancel Razorpay orders left unpaid for `pending_order_ttl_minutes`
        and give their stock back. Run periodically. Each order is handled in
        its own transaction. Returns how many were cancelled."""
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=settings.pending_order_ttl_minutes)
        seen: list[uuid.UUID] = []
        cancelled = 0

        while len(seen) < SWEEP_BATCH_LIMIT:
            order = await self.repo.lock_next_stale_order(cutoff, skip_ids=seen)
            if order is None:
                break
            seen.append(order.id)
            try:
                # A webhook may have been missed: ask Razorpay before cancelling
                if await self.payment_service.reconcile(order):
                    logger.info("Order %s was paid; confirmed by sweeper", order.order_number)
                    continue
                await self._cancel(order, "Payment was not completed in time", changed_by_id=None)
                cancelled += 1
            except AppException as exc:
                # Razorpay unreachable: leave the order alone, retry next sweep
                logger.warning("Could not expire order %s: %s", order.order_number, exc.message)
                await self.repo.rollback()
        return cancelled
