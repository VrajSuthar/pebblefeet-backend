import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestException, ConflictException, NotFoundException
from app.model.coupon_model import Coupon, DiscountType
from app.repository.coupon import CouponRepository
from app.schema.common_schema import PageSchema
from app.schema.coupon_schema import (
    AdminCouponQuerySchema,
    CouponCreatePayloadSchema,
    CouponResponseSchema,
    CouponUpdatePayloadSchema,
)

INVALID_COUPON = "This coupon code is not valid"


class CouponService:
    def __init__(self, db: AsyncSession):
        self.repo = CouponRepository(db)

    # ------------------------------ Checkout ------------------------------

    async def validate(
        self,
        code: str,
        user_id: uuid.UUID,
        subtotal: Decimal,
        for_update: bool = False,
    ) -> Coupon:
        """Return the coupon if this user may use it on this subtotal, else
        raise a message the customer can act on. `for_update` locks the row
        (used while placing the order)."""
        coupon = await self.repo.get_by_code(code.strip().upper(), for_update=for_update)
        now = datetime.now(timezone.utc)

        if coupon is None or not coupon.is_active or coupon.valid_from > now:
            raise BadRequestException(INVALID_COUPON, code="COUPON_INVALID")
        if coupon.valid_until is not None and coupon.valid_until <= now:
            raise BadRequestException("This coupon has expired", code="COUPON_EXPIRED")
        if coupon.usage_limit is not None and coupon.used_count >= coupon.usage_limit:
            raise BadRequestException(
                "This coupon has been fully redeemed", code="COUPON_EXHAUSTED"
            )
        if subtotal < coupon.min_order_amount:
            raise BadRequestException(
                f"Add items worth ₹{coupon.min_order_amount - subtotal} more to use this coupon",
                code="COUPON_MIN_ORDER",
            )
        if coupon.per_user_limit is not None:
            used = await self.repo.user_redemptions(coupon.id, user_id)
            if used >= coupon.per_user_limit:
                raise BadRequestException(
                    "You have already used this coupon", code="COUPON_ALREADY_USED"
                )
        return coupon

    async def redeem(self, coupon: Coupon) -> None:
        await self.repo.change_used_count(coupon.id, 1)

    async def release(self, coupon_id: uuid.UUID) -> None:
        await self.repo.change_used_count(coupon_id, -1)

    # ------------------------------ Admin ------------------------------

    async def _get_or_404(self, coupon_id: uuid.UUID) -> Coupon:
        coupon = await self.repo.get(coupon_id)
        if coupon is None:
            raise NotFoundException("Coupon not found")
        return coupon

    async def list_coupons(
        self, query: AdminCouponQuerySchema
    ) -> PageSchema[CouponResponseSchema]:
        coupons, total = await self.repo.list_coupons(query)
        return PageSchema[CouponResponseSchema](
            items=[CouponResponseSchema.model_validate(c) for c in coupons],
            total=total,
            page=query.page,
            page_size=query.page_size,
        )

    async def get_coupon(self, coupon_id: uuid.UUID) -> CouponResponseSchema:
        return CouponResponseSchema.model_validate(await self._get_or_404(coupon_id))

    async def create_coupon(
        self, payload: CouponCreatePayloadSchema
    ) -> CouponResponseSchema:
        if await self.repo.code_exists(payload.code):
            raise ConflictException(f"Coupon code '{payload.code}' already exists")
        coupon = await self.repo.create(Coupon(**payload.model_dump()))
        return CouponResponseSchema.model_validate(coupon)

    async def update_coupon(
        self, coupon_id: uuid.UUID, payload: CouponUpdatePayloadSchema
    ) -> CouponResponseSchema:
        coupon = await self._get_or_404(coupon_id)
        changes = payload.changes()

        if "code" in changes and await self.repo.code_exists(
            changes["code"], exclude_id=coupon.id
        ):
            raise ConflictException(f"Coupon code '{changes['code']}' already exists")

        # Check the rules against the values the coupon will end up with
        discount_type = changes.get("discount_type", coupon.discount_type)
        discount_value = changes.get("discount_value", coupon.discount_value)
        valid_from = changes.get("valid_from", coupon.valid_from)
        valid_until = changes.get("valid_until", coupon.valid_until)
        if discount_type == DiscountType.PERCENTAGE and discount_value > 100:
            raise BadRequestException("A percentage discount cannot be more than 100")
        if valid_until is not None and valid_until <= valid_from:
            raise BadRequestException("valid_until must be after valid_from")

        for field, value in changes.items():
            setattr(coupon, field, value)
        coupon = await self.repo.save(coupon)
        return CouponResponseSchema.model_validate(coupon)

    async def delete_coupon(self, coupon_id: uuid.UUID) -> None:
        # Soft delete: past orders still reference the coupon
        coupon = await self._get_or_404(coupon_id)
        coupon.is_active = False
        await self.repo.save(coupon)
