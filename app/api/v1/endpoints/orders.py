import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user
from app.api.responses import created, ok
from app.database.session import get_db
from app.model.user_model import User
from app.schema.common_schema import PageSchema
from app.schema.order_schema import (
    CancelOrderPayloadSchema,
    CheckoutPreviewPayloadSchema,
    CheckoutPreviewSchema,
    OrderListItemSchema,
    OrderQuerySchema,
    OrderResponseSchema,
    PlaceOrderPayloadSchema,
    PlaceOrderResponseSchema,
    RazorpayCheckoutSchema,
    ReturnRequestPayloadSchema,
)
from app.schema.response_schema import ResponseSchema
from app.services.order import OrderService
from app.services.payment import PaymentService
from app.services.razorpay_client import RazorpayClient, get_razorpay_client

# Every route here needs a valid access token. FastAPI runs get_current_user
# once per request, so routes that also take `user` don't repeat the lookup.
order_route = APIRouter(
    prefix="/orders",
    tags=["Orders"],
    dependencies=[Depends(get_current_user)],
)


def get_order_service(
    db: AsyncSession = Depends(get_db),
    razorpay: RazorpayClient = Depends(get_razorpay_client),
) -> OrderService:
    return OrderService(db, razorpay=razorpay)


def get_payment_service(
    db: AsyncSession = Depends(get_db),
    razorpay: RazorpayClient = Depends(get_razorpay_client),
) -> PaymentService:
    return PaymentService(db, razorpay=razorpay)


@order_route.post("/preview", response_model=ResponseSchema[CheckoutPreviewSchema])
async def preview_checkout(
    payload: CheckoutPreviewPayloadSchema,
    user: User = Depends(get_current_user),
    service: OrderService = Depends(get_order_service),
):
    """Totals for the checkout screen, including the coupon. Reserves nothing."""
    return ok("Checkout summary", await service.preview(user, payload))


@order_route.post(
    "", response_model=ResponseSchema[PlaceOrderResponseSchema], status_code=201
)
async def place_order(
    payload: PlaceOrderPayloadSchema,
    user: User = Depends(get_current_user),
    service: OrderService = Depends(get_order_service),
):
    """Creates the order from the cart. For Razorpay, open Checkout with
    `data.payment`, then call POST /payments/verify."""
    result = await service.place_order(user, payload)
    return created("Order placed", result)


@order_route.get("", response_model=ResponseSchema[PageSchema[OrderListItemSchema]])
async def list_orders(
    query: OrderQuerySchema = Query(),
    user: User = Depends(get_current_user),
    service: OrderService = Depends(get_order_service),
):
    return ok("Orders fetched", await service.list_orders(user, query))


@order_route.get("/{order_id}", response_model=ResponseSchema[OrderResponseSchema])
async def get_order(
    order_id: uuid.UUID,
    user: User = Depends(get_current_user),
    service: OrderService = Depends(get_order_service),
):
    return ok("Order fetched", await service.get_order(user, order_id))


@order_route.post(
    "/{order_id}/pay", response_model=ResponseSchema[RazorpayCheckoutSchema]
)
async def retry_payment(
    order_id: uuid.UUID,
    user: User = Depends(get_current_user),
    service: PaymentService = Depends(get_payment_service),
):
    """Checkout options again for an unpaid order (payment failed or app closed)."""
    return ok("Payment started", await service.retry_checkout(user, order_id))


@order_route.post("/{order_id}/cancel", response_model=ResponseSchema[OrderResponseSchema])
async def cancel_order(
    order_id: uuid.UUID,
    payload: CancelOrderPayloadSchema,
    user: User = Depends(get_current_user),
    service: OrderService = Depends(get_order_service),
):
    return ok("Order cancelled", await service.cancel_order(user, order_id, payload))


@order_route.post("/{order_id}/return", response_model=ResponseSchema[OrderResponseSchema])
async def request_return(
    order_id: uuid.UUID,
    payload: ReturnRequestPayloadSchema,
    user: User = Depends(get_current_user),
    service: OrderService = Depends(get_order_service),
):
    return ok("Return requested", await service.request_return(user, order_id, payload))
