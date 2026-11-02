import uuid

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.model.catalog_model import Product
from app.model.wishlist_model import WishlistItem


class WishlistRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_items(self, user_id: uuid.UUID) -> list[WishlistItem]:
        # Archived products drop out of the list without losing the row
        result = await self.db.execute(
            select(WishlistItem)
            .join(WishlistItem.product)
            .where(WishlistItem.user_id == user_id, Product.is_active.is_(True))
            .options(
                selectinload(WishlistItem.product).selectinload(Product.variants),
                selectinload(WishlistItem.product).selectinload(Product.images),
            )
            .order_by(WishlistItem.created_at.desc())
        )
        return list(result.scalars().all())

    async def product_is_active(self, product_id: uuid.UUID) -> bool:
        product = await self.db.get(Product, product_id)
        return product is not None and product.is_active

    async def add(self, user_id: uuid.UUID, product_id: uuid.UUID) -> None:
        # Adding twice is a no-op, not an error
        await self.db.execute(
            insert(WishlistItem)
            .values(id=uuid.uuid4(), user_id=user_id, product_id=product_id)
            .on_conflict_do_nothing(constraint="uq_user_product_wishlist")
        )
        await self.db.commit()

    async def remove(self, user_id: uuid.UUID, product_id: uuid.UUID) -> None:
        await self.db.execute(
            delete(WishlistItem).where(
                WishlistItem.user_id == user_id, WishlistItem.product_id == product_id
            )
        )
        await self.db.commit()
