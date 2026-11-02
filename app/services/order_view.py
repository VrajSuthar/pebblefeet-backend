"""Order -> response schema. Shared by the order and payment services."""

from datetime import datetime, timedelta, timezone

from app.core.settings import settings
from app.model.order_model import Order, OrderStatus, PaymentMethod, PaymentStatus
from app.schema.order_schema import (
    AdminOrderCustomerSchema,
    AdminOrderListItemSchema,
    AdminOrderResponseSchema,
    OrderItemResponseSchema,
    OrderListItemSchema,
    OrderResponseSchema,
    OrderStatusHistorySchema,
    PaymentSummarySchema,
)

# A customer may cancel until the parcel is packed
CUSTOMER_CANCELLABLE = {OrderStatus.PENDING, OrderStatus.CONFIRMED}


def can_cancel(order: Order) -> bool:
    return order.status in CUSTOMER_CANCELLABLE


def can_return(order: Order) -> bool:
    if order.status != OrderStatus.DELIVERED or order.delivered_at is None:
        return False
    deadline = order.delivered_at + timedelta(days=settings.return_window_days)
    return datetime.now(timezone.utc) <= deadline


def can_pay(order: Order) -> bool:
    return (
        order.status == OrderStatus.PENDING
        and order.payment_method == PaymentMethod.RAZORPAY
        and order.payment_status != PaymentStatus.PAID
    )


def _detail_fields(order: Order) -> dict:
    return dict(
        id=order.id,
        order_number=order.order_number,
        status=order.status,
        payment_status=order.payment_status,
        payment_method=order.payment_method,
        subtotal=order.subtotal,
        discount_amount=order.discount_amount,
        shipping_fee=order.shipping_fee,
        tax_amount=order.tax_amount,
        total_amount=order.total_amount,
        currency=order.currency,
        coupon_code=order.coupon.code if order.coupon else None,
        shipping_address=order.shipping_address,
        courier_name=order.courier_name,
        tracking_number=order.tracking_number,
        shipped_at=order.shipped_at,
        delivered_at=order.delivered_at,
        cancelled_at=order.cancelled_at,
        cancellation_reason=order.cancellation_reason,
        customer_note=order.customer_note,
        created_at=order.created_at,
        items=[OrderItemResponseSchema.model_validate(i) for i in order.items],
        status_history=[
            OrderStatusHistorySchema.model_validate(h) for h in order.status_history
        ],
        payments=[
            PaymentSummarySchema.model_validate(p)
            for p in sorted(order.payments, key=lambda p: p.created_at)
        ],
        can_cancel=can_cancel(order),
        can_return=can_return(order),
        can_pay=can_pay(order),
    )


def to_order_response(order: Order) -> OrderResponseSchema:
    return OrderResponseSchema(**_detail_fields(order))


def to_admin_order_response(order: Order) -> AdminOrderResponseSchema:
    return AdminOrderResponseSchema(
        **_detail_fields(order),
        customer=AdminOrderCustomerSchema.model_validate(order.user),
    )


def _list_fields(order: Order) -> dict:
    first = order.items[0] if order.items else None
    return dict(
        id=order.id,
        order_number=order.order_number,
        status=order.status,
        payment_status=order.payment_status,
        payment_method=order.payment_method,
        total_amount=order.total_amount,
        item_count=sum(i.quantity for i in order.items),
        preview_name=first.product_name if first else None,
        preview_image_url=first.image_url if first else None,
        created_at=order.created_at,
    )


def to_order_list_item(order: Order) -> OrderListItemSchema:
    return OrderListItemSchema(**_list_fields(order))


def to_admin_order_list_item(order: Order) -> AdminOrderListItemSchema:
    return AdminOrderListItemSchema(
        **_list_fields(order),
        customer_name=f"{order.user.first_name} {order.user.last_name}",
        customer_email=order.user.email,
    )
