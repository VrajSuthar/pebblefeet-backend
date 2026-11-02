import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundException
from app.model.user_model import User
from app.repository.review import ReviewRepository
from app.repository.wishlist import WishlistRepository
from app.schema.wishlist_schema import WishlistAddPayloadSchema, WishlistItemSchema
from app.services.product import ProductService


class WishlistService:
    def __init__(self, db: AsyncSession):
        self.repo = WishlistRepository(db)
        self.review_repo = ReviewRepository(db)

    async def list_items(self, user: User) -> list[WishlistItemSchema]:
        items = await self.repo.list_items(user.id)
        ratings = await self.review_repo.summaries([i.product_id for i in items])
        return [
            WishlistItemSchema(
                product=ProductService.to_list_item(item.product, ratings.get(item.product_id)),
                added_at=item.created_at,
            )
            for item in items
        ]

    async def add(
        self, user: User, payload: WishlistAddPayloadSchema
    ) -> list[WishlistItemSchema]:
        if not await self.repo.product_is_active(payload.product_id):
            raise NotFoundException("Product not found")
        await self.repo.add(user.id, payload.product_id)
        return await self.list_items(user)

    async def remove(self, user: User, product_id: uuid.UUID) -> list[WishlistItemSchema]:
        # Removing something that isn't there is fine (idempotent)
        await self.repo.remove(user.id, product_id)
        return await self.list_items(user)
