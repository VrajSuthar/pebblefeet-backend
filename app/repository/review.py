import uuid
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.model.catalog_model import Product
from app.model.review_model import Review
from app.schema.review_schema import AdminReviewQuerySchema, ReviewQuerySchema


class ReviewRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get(self, review_id: uuid.UUID) -> Review | None:
        result = await self.db.execute(
            select(Review).where(Review.id == review_id).options(selectinload(Review.user))
        )
        return result.scalars().first()

    async def get_for_user(self, user_id: uuid.UUID, product_id: uuid.UUID) -> Review | None:
        result = await self.db.execute(
            select(Review).where(Review.user_id == user_id, Review.product_id == product_id)
        )
        return result.scalars().first()

    async def product_is_active(self, product_id: uuid.UUID) -> bool:
        product = await self.db.get(Product, product_id)
        return product is not None and product.is_active

    async def _page(self, conditions: list, offset: int, limit: int) -> tuple[list[Review], int]:
        total = await self.db.scalar(select(func.count()).select_from(Review).where(*conditions))
        result = await self.db.execute(
            select(Review)
            .where(*conditions)
            .options(selectinload(Review.user))
            .order_by(Review.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all()), total or 0

    async def list_for_product(
        self, product_id: uuid.UUID, query: ReviewQuerySchema
    ) -> tuple[list[Review], int]:
        conditions = [Review.product_id == product_id, Review.is_approved.is_(True)]
        if query.rating is not None:
            conditions.append(Review.rating == query.rating)
        return await self._page(conditions, query.offset, query.page_size)

    async def admin_list(self, query: AdminReviewQuerySchema) -> tuple[list[Review], int]:
        conditions = []
        if query.product_id is not None:
            conditions.append(Review.product_id == query.product_id)
        if query.is_approved is not None:
            conditions.append(Review.is_approved.is_(query.is_approved))
        if query.rating is not None:
            conditions.append(Review.rating == query.rating)
        return await self._page(conditions, query.offset, query.page_size)

    async def distribution(self, product_id: uuid.UUID) -> dict[int, int]:
        result = await self.db.execute(
            select(Review.rating, func.count())
            .where(Review.product_id == product_id, Review.is_approved.is_(True))
            .group_by(Review.rating)
        )
        return {rating: count for rating, count in result.all()}

    async def summaries(
        self, product_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, tuple[Decimal, int]]:
        """Average rating and review count per product, approved reviews only."""
        if not product_ids:
            return {}
        result = await self.db.execute(
            select(Review.product_id, func.avg(Review.rating), func.count())
            .where(Review.product_id.in_(product_ids), Review.is_approved.is_(True))
            .group_by(Review.product_id)
        )
        return {pid: (Decimal(avg), count) for pid, avg, count in result.all()}

    async def create(self, review: Review) -> Review:
        self.db.add(review)
        await self.db.commit()
        await self.db.refresh(review, attribute_names=["user", "created_at", "updated_at"])
        return review

    async def save(self, review: Review) -> Review:
        await self.db.commit()
        await self.db.refresh(review)
        await self.db.refresh(review, attribute_names=["user"])
        return review

    async def delete(self, review: Review) -> None:
        await self.db.delete(review)
        await self.db.commit()
