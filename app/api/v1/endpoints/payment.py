from fastapi import APIRouter, Depends, Header, Request
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user
from app.api.responses import ok
from app.database.redis import get_redis
from app.database.session import get_db
from app.model.user_model import User
from app.schema.order_schema import OrderResponseSchema, VerifyPaymentPayloadSchema
from app.schema.response_schema import ResponseSchema
from app.services.payment import PaymentService
from app.services.razorpay_client import RazorpayClient, get_razorpay_client

payment_route = APIRouter(prefix="/payments", tags=["Payments"])


def get_payment_service(
    db: AsyncSession = Depends(get_db),
    razorpay: RazorpayClient = Depends(get_razorpay_client),
) -> PaymentService:
    return PaymentService(db, razorpay=razorpay)


@payment_route.post("/verify", response_model=ResponseSchema[OrderResponseSchema])
async def verify_payment(
    payload: VerifyPaymentPayloadSchema,
    user: User = Depends(get_current_user),
    service: PaymentService = Depends(get_payment_service),
):
    """Call from Razorpay Checkout's `handler` with the three values it returns."""
    return ok("Payment successful", await service.verify(user, payload))


# No JWT: Razorpay calls this. It is authenticated by the signature header.
@payment_route.post("/webhook/razorpay", response_model=ResponseSchema[None])
async def razorpay_webhook(
    request: Request,
    x_razorpay_signature: str = Header(default=""),
    x_razorpay_event_id: str | None = Header(default=None),
    service: PaymentService = Depends(get_payment_service),
    redis: Redis = Depends(get_redis),
):
    # The signature is over the exact raw bytes, so read the body unparsed
    body = await request.body()
    await service.handle_webhook(body, x_razorpay_signature, x_razorpay_event_id, redis)
    return ok("Webhook processed")
