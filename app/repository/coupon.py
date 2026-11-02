import uuid

from sqlalchemy import exists, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.model.coupon_model import Coupon
from app.model.order_model import Order, OrderStatus
from app.repository.utils import LIKE_ESCAPE, contains_pattern
from app.schema.coupon_schema import AdminCouponQuerySchema


class CouponRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get(self, coupon_id: uuid.UUID) -> Coupon | None:
        return await self.db.get(Coupon, coupon_id)

    async def get_by_code(self, code: str, for_update: bool = False) -> Coupon | None:
        statement = select(Coupon).where(Coupon.code == code)
        if for_update:
            # Locks the row until commit so two checkouts can't both take the
            # last use of a limited coupon
            statement = statement.with_for_update()
        result = await self.db.execute(statement)
        return result.scalars().first()

    async def code_exists(self, code: str, exclude_id: uuid.UUID | None = None) -> bool:
        condition = Coupon.code == code
        if exclude_id is not None:
            condition = condition & (Coupon.id != exclude_id)
        return bool(await self.db.scalar(select(exists().where(condition))))

    async def user_redemptions(self, coupon_id: uuid.UUID, user_id: uuid.UUID) -> int:
        # Cancelled orders give the use back
        return (
            await self.db.scalar(
                select(func.count()).where(
                    Order.coupon_id == coupon_id,
                    Order.user_id == user_id,
                    Order.status != OrderStatus.CANCELLED,
                )
            )
            or 0
        )

    async def change_used_count(self, coupon_id: uuid.UUID, delta: int) -> None:
        # Not committed: part of the order's transaction
        await self.db.execute(
            update(Coupon)
            .where(Coupon.id == coupon_id)
            .values(used_count=func.greatest(Coupon.used_count + delta, 0))
        )

    async def list_coupons(self, query: AdminCouponQuerySchema) -> tuple[list[Coupon], int]:
        conditions = []
        if query.search:
            conditions.append(
                Coupon.code.ilike(contains_pattern(query.search), escape=LIKE_ESCAPE)
            )
        if query.is_active is not None:
            conditions.append(Coupon.is_active.is_(query.is_active))

        total = await self.db.scalar(
            select(func.count()).select_from(Coupon).where(*conditions)
        )
        result = await self.db.execute(
            select(Coupon)
            .where(*conditions)
            .order_by(Coupon.created_at.desc())
            .offset(query.offset)
            .limit(query.page_size)
        )
        return list(result.scalars().all()), total or 0

    async def create(self, coupon: Coupon) -> Coupon:
        self.db.add(coupon)
        await self.db.commit()
        await self.db.refresh(coupon)
        return coupon

    async def save(self, coupon: Coupon) -> Coupon:
        await self.db.commit()
        await self.db.refresh(coupon)
        return coupon
