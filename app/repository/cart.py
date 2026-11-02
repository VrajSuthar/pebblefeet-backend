import uuid

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.model.cart_model import CartItem
from app.model.catalog_model import Product, ProductVariant


class CartRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_items(self, user_id: uuid.UUID) -> list[CartItem]:
        result = await self.db.execute(
            select(CartItem)
            .where(CartItem.user_id == user_id)
            .options(
                selectinload(CartItem.variant)
                .selectinload(ProductVariant.product)
                .selectinload(Product.images)
            )
            .order_by(CartItem.created_at)
            .execution_options(populate_existing=True)
        )
        return list(result.scalars().all())

    async def get_item(self, user_id: uuid.UUID, item_id: uuid.UUID) -> CartItem | None:
        result = await self.db.execute(
            select(CartItem)
            .where(CartItem.id == item_id, CartItem.user_id == user_id)
            .options(selectinload(CartItem.variant).selectinload(ProductVariant.product))
        )
        return result.scalars().first()

    async def get_quantity(self, user_id: uuid.UUID, variant_id: uuid.UUID) -> int:
        return (
            await self.db.scalar(
                select(CartItem.quantity).where(
                    CartItem.user_id == user_id, CartItem.variant_id == variant_id
                )
            )
            or 0
        )

    async def get_variant(self, variant_id: uuid.UUID) -> ProductVariant | None:
        result = await self.db.execute(
            select(ProductVariant)
            .where(ProductVariant.id == variant_id)
            .options(selectinload(ProductVariant.product))
        )
        return result.scalars().first()

    async def add_quantity(
        self, user_id: uuid.UUID, variant_id: uuid.UUID, quantity: int, cap: int
    ) -> None:
        # Upsert so two quick "add" taps can't trip the (user, variant) unique key
        statement = insert(CartItem).values(
            id=uuid.uuid4(), user_id=user_id, variant_id=variant_id, quantity=quantity
        )
        statement = statement.on_conflict_do_update(
            constraint="uq_user_variant_cart",
            set_={
                "quantity": func.least(CartItem.quantity + statement.excluded.quantity, cap),
                "updated_at": func.now(),
            },
        )
        await self.db.execute(statement)
        await self.db.commit()

    async def count_items(self, user_id: uuid.UUID) -> int:
        return (
            await self.db.scalar(
                select(func.count()).where(CartItem.user_id == user_id)
            )
            or 0
        )

    async def save(self) -> None:
        await self.db.commit()

    async def delete_item(self, item: CartItem) -> None:
        await self.db.delete(item)
        await self.db.commit()

    async def clear(self, user_id: uuid.UUID, commit: bool = True) -> None:
        await self.db.execute(delete(CartItem).where(CartItem.user_id == user_id))
        if commit:
            await self.db.commit()
