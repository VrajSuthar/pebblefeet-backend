"""Store-owner endpoints. Every route here requires an admin account.
Product and category management lives on /products (admin-only writes)."""

import uuid

from fastapi import APIRouter, Depends, Query
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import require_admin
from app.api.responses import created, ok
from app.database.redis import get_redis
from app.database.session import get_db
from app.model.user_model import User
from app.schema.common_schema import PageSchema
from app.schema.coupon_schema import (
    AdminCouponQuerySchema,
    CouponCreatePayloadSchema,
    CouponResponseSchema,
    CouponUpdatePayloadSchema,
)
from app.schema.order_schema import (
    AdminOrderListItemSchema,
    AdminOrderQuerySchema,
    AdminOrderResponseSchema,
    AdminOrderStatusPayloadSchema,
    DashboardSchema,
)
from app.schema.response_schema import ResponseSchema
from app.schema.review_schema import (
    AdminReviewModeratePayloadSchema,
    AdminReviewQuerySchema,
    ReviewResponseSchema,
)
from app.schema.user_schema import (
    AdminUserQuerySchema,
    AdminUserSchema,
    AdminUserUpdatePayloadSchema,
)
from app.services.coupon import CouponService
from app.services.dashboard import DashboardService
from app.services.order import OrderService
from app.services.razorpay_client import RazorpayClient, get_razorpay_client
from app.services.review import ReviewService
from app.services.user import UserService

admin_route = APIRouter(
    prefix="/admin",
    tags=["Admin"],
    dependencies=[Depends(require_admin)],
)


def get_order_service(
    db: AsyncSession = Depends(get_db),
    razorpay: RazorpayClient = Depends(get_razorpay_client),
) -> OrderService:
    return OrderService(db, razorpay=razorpay)


def get_user_service(
    db: AsyncSession = Depends(get_db), redis: Redis = Depends(get_redis)
) -> UserService:
    return UserService(db, redis=redis)


def get_coupon_service(db: AsyncSession = Depends(get_db)) -> CouponService:
    return CouponService(db)


def get_review_service(db: AsyncSession = Depends(get_db)) -> ReviewService:
    return ReviewService(db)


def get_dashboard_service(db: AsyncSession = Depends(get_db)) -> DashboardService:
    return DashboardService(db)


# ------------------------------ Dashboard ------------------------------


@admin_route.get("/dashboard", response_model=ResponseSchema[DashboardSchema])
async def dashboard(service: DashboardService = Depends(get_dashboard_service)):
    return ok("Dashboard fetched", await service.summary())


# ------------------------------ Orders ------------------------------


@admin_route.get(
    "/orders", response_model=ResponseSchema[PageSchema[AdminOrderListItemSchema]]
)
async def list_orders(
    query: AdminOrderQuerySchema = Query(),
    service: OrderService = Depends(get_order_service),
):
    return ok("Orders fetched", await service.admin_list_orders(query))


@admin_route.get("/orders/{order_id}", response_model=ResponseSchema[AdminOrderResponseSchema])
async def get_order(order_id: uuid.UUID, service: OrderService = Depends(get_order_service)):
    return ok("Order fetched", await service.admin_get_order(order_id))


@admin_route.patch(
    "/orders/{order_id}/status", response_model=ResponseSchema[AdminOrderResponseSchema]
)
async def update_order_status(
    order_id: uuid.UUID,
    payload: AdminOrderStatusPayloadSchema,
    admin: User = Depends(require_admin),
    service: OrderService = Depends(get_order_service),
):
    """processing -> shipped (needs courier + tracking) -> delivered, or
    cancelled / returned (both restock and refund online payments)."""
    return ok("Order updated", await service.admin_update_status(admin, order_id, payload))


# ------------------------------ Customers ------------------------------


@admin_route.get("/users", response_model=ResponseSchema[PageSchema[AdminUserSchema]])
async def list_users(
    query: AdminUserQuerySchema = Query(),
    service: UserService = Depends(get_user_service),
):
    return ok("Users fetched", await service.admin_list_users(query))


@admin_route.get("/users/{user_id}", response_model=ResponseSchema[AdminUserSchema])
async def get_user(user_id: uuid.UUID, service: UserService = Depends(get_user_service)):
    return ok("User fetched", await service.admin_get_user(user_id))


@admin_route.patch("/users/{user_id}", response_model=ResponseSchema[AdminUserSchema])
async def update_user(
    user_id: uuid.UUID,
    payload: AdminUserUpdatePayloadSchema,
    admin: User = Depends(require_admin),
    service: UserService = Depends(get_user_service),
):
    """Block/unblock (is_active) or change role. Blocking logs the user out everywhere."""
    return ok("User updated", await service.admin_update_user(admin, user_id, payload))


# ------------------------------ Coupons ------------------------------


@admin_route.get("/coupons", response_model=ResponseSchema[PageSchema[CouponResponseSchema]])
async def list_coupons(
    query: AdminCouponQuerySchema = Query(),
    service: CouponService = Depends(get_coupon_service),
):
    return ok("Coupons fetched", await service.list_coupons(query))


@admin_route.post("/coupons", response_model=ResponseSchema[CouponResponseSchema], status_code=201)
async def create_coupon(
    payload: CouponCreatePayloadSchema, service: CouponService = Depends(get_coupon_service)
):
    return created("Coupon created", await service.create_coupon(payload))


@admin_route.get("/coupons/{coupon_id}", response_model=ResponseSchema[CouponResponseSchema])
async def get_coupon(coupon_id: uuid.UUID, service: CouponService = Depends(get_coupon_service)):
    return ok("Coupon fetched", await service.get_coupon(coupon_id))


@admin_route.patch("/coupons/{coupon_id}", response_model=ResponseSchema[CouponResponseSchema])
async def update_coupon(
    coupon_id: uuid.UUID,
    payload: CouponUpdatePayloadSchema,
    service: CouponService = Depends(get_coupon_service),
):
    return ok("Coupon updated", await service.update_coupon(coupon_id, payload))


@admin_route.delete("/coupons/{coupon_id}", response_model=ResponseSchema[None])
async def delete_coupon(
    coupon_id: uuid.UUID, service: CouponService = Depends(get_coupon_service)
):
    await service.delete_coupon(coupon_id)
    return ok("Coupon deleted")


# ------------------------------ Reviews ------------------------------


@admin_route.get("/reviews", response_model=ResponseSchema[PageSchema[ReviewResponseSchema]])
async def list_reviews(
    query: AdminReviewQuerySchema = Query(),
    service: ReviewService = Depends(get_review_service),
):
    return ok("Reviews fetched", await service.admin_list(query))


@admin_route.patch("/reviews/{review_id}", response_model=ResponseSchema[ReviewResponseSchema])
async def moderate_review(
    review_id: uuid.UUID,
    payload: AdminReviewModeratePayloadSchema,
    service: ReviewService = Depends(get_review_service),
):
    """Hide (is_approved=false) or restore a review."""
    return ok("Review updated", await service.moderate(review_id, payload))
