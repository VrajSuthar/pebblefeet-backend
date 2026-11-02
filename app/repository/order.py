import uuid
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal

from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.model.catalog_model import Product, ProductVariant
from app.model.order_model import (
    Order,
    OrderItem,
    OrderStatus,
    OrderStatusHistory,
    PaymentMethod,
    PaymentStatus,
)
from app.model.payment_model import Payment
from app.model.user_model import User, UserAddress, UserRole
from app.repository.utils import LIKE_ESCAPE, contains_pattern
from app.schema.order_schema import AdminOrderQuerySchema, OrderQuerySchema

_DETAIL_OPTIONS = (
    selectinload(Order.items),
    selectinload(Order.payments),
    selectinload(Order.status_history),
    selectinload(Order.coupon),
    selectinload(Order.user),
)

LOW_STOCK_THRESHOLD = 5


class OrderRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def commit(self) -> None:
        await self.db.commit()

    async def rollback(self) -> None:
        await self.db.rollback()

    def add(self, instance) -> None:
        self.db.add(instance)

    async def flush(self) -> None:
        await self.db.flush()

    # ------------------------------ Stock ------------------------------

    async def lock_variants(self, variant_ids: list[uuid.UUID]) -> list[ProductVariant]:
        # FOR UPDATE until commit: two checkouts for the last bar of soap queue
        # up here instead of both succeeding. Sorted ids keep the lock order
        # stable, which avoids deadlocks between concurrent orders.
        result = await self.db.execute(
            select(ProductVariant)
            .where(ProductVariant.id.in_(sorted(variant_ids)))
            .order_by(ProductVariant.id)
            .options(selectinload(ProductVariant.product).selectinload(Product.images))
            .with_for_update(of=ProductVariant)
            .execution_options(populate_existing=True)
        )
        return list(result.scalars().all())

    async def restock(self, order: Order) -> None:
        quantities = {i.variant_id: i.quantity for i in order.items if i.variant_id}
        if not quantities:
            return
        for variant in await self.lock_variants(list(quantities)):
            variant.stock += quantities[variant.id]

    async def get_user_address(
        self, user_id: uuid.UUID, address_id: uuid.UUID
    ) -> UserAddress | None:
        result = await self.db.execute(
            select(UserAddress).where(
                UserAddress.id == address_id, UserAddress.user_id == user_id
            )
        )
        return result.scalars().first()

    # ------------------------------ Orders ------------------------------

    async def order_number_exists(self, order_number: str) -> bool:
        return bool(
            await self.db.scalar(
                select(func.count()).where(Order.order_number == order_number)
            )
        )

    async def get_order(
        self,
        order_id: uuid.UUID,
        user_id: uuid.UUID | None = None,
        for_update: bool = False,
    ) -> Order | None:
        """`user_id` scopes the lookup to one customer's orders."""
        statement = (
            select(Order)
            .where(Order.id == order_id)
            .options(*_DETAIL_OPTIONS)
            .execution_options(populate_existing=True)
        )
        if user_id is not None:
            statement = statement.where(Order.user_id == user_id)
        if for_update:
            statement = statement.with_for_update(of=Order)
        result = await self.db.execute(statement)
        return result.scalars().first()

    async def _paginate(
        self, statement: Select, conditions: list, offset: int, limit: int
    ) -> tuple[list[Order], int]:
        total = await self.db.scalar(
            select(func.count()).select_from(Order).where(*conditions)
        )
        result = await self.db.execute(
            statement.where(*conditions)
            .order_by(Order.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all()), total or 0

    async def list_orders(
        self, user_id: uuid.UUID, query: OrderQuerySchema
    ) -> tuple[list[Order], int]:
        conditions = [Order.user_id == user_id]
        if query.status is not None:
            conditions.append(Order.status == query.status)
        return await self._paginate(
            select(Order).options(selectinload(Order.items)),
            conditions,
            query.offset,
            query.page_size,
        )

    async def admin_list_orders(
        self, query: AdminOrderQuerySchema
    ) -> tuple[list[Order], int]:
        conditions = []
        if query.status is not None:
            conditions.append(Order.status == query.status)
        if query.payment_status is not None:
            conditions.append(Order.payment_status == query.payment_status)
        if query.payment_method is not None:
            conditions.append(Order.payment_method == query.payment_method)
        if query.date_from is not None:
            conditions.append(
                Order.created_at >= datetime.combine(query.date_from, time.min, timezone.utc)
            )
        if query.date_to is not None:
            conditions.append(
                Order.created_at
                < datetime.combine(query.date_to + timedelta(days=1), time.min, timezone.utc)
            )
        if query.search:
            term = contains_pattern(query.search)
            conditions.append(
                or_(
                    Order.order_number.ilike(term, escape=LIKE_ESCAPE),
                    Order.user_id.in_(
                        select(User.id).where(
                            or_(
                                User.email.ilike(term, escape=LIKE_ESCAPE),
                                User.phone_number.ilike(term, escape=LIKE_ESCAPE),
                            )
                        )
                    ),
                )
            )
        return await self._paginate(
            select(Order).options(selectinload(Order.items), selectinload(Order.user)),
            conditions,
            query.offset,
            query.page_size,
        )

    async def lock_next_stale_order(
        self, created_before: datetime, skip_ids: list[uuid.UUID]
    ) -> Order | None:
        """One unpaid Razorpay order older than `created_before`, locked.
        SKIP LOCKED: several app instances can sweep at once, and an order
        being paid right now (locked by the payment flow) is left alone."""
        statement = (
            select(Order)
            .where(
                Order.status == OrderStatus.PENDING,
                Order.payment_method == PaymentMethod.RAZORPAY,
                Order.created_at < created_before,
            )
            .order_by(Order.created_at)
            .limit(1)
            .options(*_DETAIL_OPTIONS)
            .with_for_update(of=Order, skip_locked=True)
            .execution_options(populate_existing=True)
        )
        if skip_ids:
            statement = statement.where(Order.id.not_in(skip_ids))
        result = await self.db.execute(statement)
        return result.scalars().first()

    def add_history(
        self,
        order: Order,
        status: OrderStatus,
        note: str | None = None,
        changed_by_id: uuid.UUID | None = None,
    ) -> None:
        order.status_history.append(
            OrderStatusHistory(status=status, note=note, changed_by_id=changed_by_id)
        )

    async def has_delivered_purchase(self, user_id: uuid.UUID, product_id: uuid.UUID) -> bool:
        return bool(
            await self.db.scalar(
                select(func.count())
                .select_from(OrderItem)
                .join(Order, Order.id == OrderItem.order_id)
                .join(ProductVariant, ProductVariant.id == OrderItem.variant_id)
                .where(
                    Order.user_id == user_id,
                    Order.status.in_(
                        [OrderStatus.DELIVERED, OrderStatus.RETURN_REQUESTED]
                    ),
                    ProductVariant.product_id == product_id,
                )
            )
        )

    # ------------------------------ Payments ------------------------------

    async def get_payment_by_razorpay_order(
        self, razorpay_order_id: str
    ) -> Payment | None:
        result = await self.db.execute(
            select(Payment).where(Payment.razorpay_order_id == razorpay_order_id)
        )
        return result.scalars().first()

    async def get_payment_by_razorpay_payment(
        self, razorpay_payment_id: str
    ) -> Payment | None:
        result = await self.db.execute(
            select(Payment).where(Payment.razorpay_payment_id == razorpay_payment_id)
        )
        return result.scalars().first()

    # ------------------------------ Dashboard ------------------------------

    @staticmethod
    def _revenue_condition():
        # Money actually received: online payments, or COD once paid on delivery
        return Order.payment_status == PaymentStatus.PAID

    async def revenue_and_count_since(self, since: datetime) -> tuple[Decimal, int]:
        row = (
            await self.db.execute(
                select(
                    func.coalesce(
                        func.sum(Order.total_amount).filter(self._revenue_condition()), 0
                    ),
                    func.count().filter(Order.status != OrderStatus.CANCELLED),
                ).where(Order.created_at >= since)
            )
        ).one()
        return row[0], row[1]

    async def count_by_status(self) -> dict[OrderStatus, int]:
        result = await self.db.execute(
            select(Order.status, func.count()).group_by(Order.status)
        )
        return {status: count for status, count in result.all()}

    async def customer_counts(self, since: datetime) -> tuple[int, int]:
        row = (
            await self.db.execute(
                select(
                    func.count(),
                    func.count().filter(User.created_at >= since),
                ).where(User.role == UserRole.CUSTOMER)
            )
        ).one()
        return row[0], row[1]

    async def low_stock_variants(self, limit: int = 20) -> list[ProductVariant]:
        result = await self.db.execute(
            select(ProductVariant)
            .join(ProductVariant.product)
            .where(
                ProductVariant.is_active.is_(True),
                Product.is_active.is_(True),
                ProductVariant.stock <= LOW_STOCK_THRESHOLD,
            )
            .options(selectinload(ProductVariant.product))
            .order_by(ProductVariant.stock, ProductVariant.sku)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def top_products_since(self, since: datetime, limit: int = 5) -> list[tuple]:
        result = await self.db.execute(
            select(
                OrderItem.product_name,
                func.sum(OrderItem.quantity),
                func.sum(OrderItem.total_price),
            )
            .join(Order, Order.id == OrderItem.order_id)
            .where(Order.created_at >= since, self._revenue_condition())
            .group_by(OrderItem.product_name)
            .order_by(func.sum(OrderItem.quantity).desc())
            .limit(limit)
        )
        return [tuple(row) for row in result.all()]

