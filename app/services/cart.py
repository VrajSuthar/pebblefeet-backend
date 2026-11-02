import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestException, NotFoundException
from app.core.settings import settings
from app.model.cart_model import CartItem
from app.model.catalog_model import ProductVariant
from app.model.user_model import User
from app.repository.cart import CartRepository
from app.schema.cart_schema import (
    CartItemAddPayloadSchema,
    CartItemResponseSchema,
    CartItemUpdatePayloadSchema,
    CartResponseSchema,
)
from app.services.pricing import ZERO, money, shipping_for

MAX_CART_LINES = 30


def availability_issue(variant: ProductVariant, quantity: int) -> str | None:
    """Why `quantity` of this variant can't be bought right now, or None."""
    if not variant.is_active or not variant.product.is_active:
        return "This item is no longer available"
    if variant.stock <= 0:
        return "Out of stock"
    if quantity > variant.stock:
        return f"Only {variant.stock} left in stock"
    return None


def variant_image_url(variant: ProductVariant) -> str | None:
    # Prefer a photo of this exact pack, then the product's primary photo
    images = variant.product.images
    for candidate in (
        next((i for i in images if i.variant_id == variant.id), None),
        next((i for i in images if i.is_primary), None),
        images[0] if images else None,
    ):
        if candidate is not None:
            return candidate.image_url
    return None


class CartService:
    def __init__(self, db: AsyncSession):
        self.repo = CartRepository(db)

    @staticmethod
    def _to_item(item: CartItem) -> CartItemResponseSchema:
        variant = item.variant
        issue = availability_issue(variant, item.quantity)
        return CartItemResponseSchema(
            id=item.id,
            variant_id=variant.id,
            product_id=variant.product_id,
            product_name=variant.product.name,
            product_slug=variant.product.slug,
            variant_name=variant.name,
            sku=variant.sku,
            image_url=variant_image_url(variant),
            unit_price=variant.price,
            mrp=variant.mrp,
            quantity=item.quantity,
            line_total=money(variant.price * item.quantity),
            available_stock=max(variant.stock, 0),
            is_available=issue is None,
            issue=issue,
        )

    async def get_cart(self, user: User) -> CartResponseSchema:
        items = [self._to_item(i) for i in await self.repo.list_items(user.id)]
        # Totals only count what can actually be bought
        subtotal = money(sum((i.line_total for i in items if i.is_available), ZERO))
        shipping = shipping_for(subtotal)
        return CartResponseSchema(
            items=items,
            item_count=sum(i.quantity for i in items),
            subtotal=subtotal,
            shipping_fee=shipping,
            total=money(subtotal + shipping),
            amount_for_free_shipping=(
                money(settings.free_shipping_threshold - subtotal)
                if 0 < subtotal < settings.free_shipping_threshold
                else ZERO
            ),
            has_issues=any(not i.is_available for i in items),
        )

    async def _get_item_or_404(self, user: User, item_id: uuid.UUID) -> CartItem:
        item = await self.repo.get_item(user.id, item_id)
        if item is None:
            raise NotFoundException("Cart item not found")
        return item

    async def add_item(
        self, user: User, payload: CartItemAddPayloadSchema
    ) -> CartResponseSchema:
        variant = await self.repo.get_variant(payload.variant_id)
        if variant is None:
            raise NotFoundException("Product not found")

        current = await self.repo.get_quantity(user.id, variant.id)
        if current == 0 and await self.repo.count_items(user.id) >= MAX_CART_LINES:
            raise BadRequestException(f"A cart can hold at most {MAX_CART_LINES} items")

        wanted = current + payload.quantity
        if wanted > settings.max_quantity_per_item:
            raise BadRequestException(
                f"You can buy at most {settings.max_quantity_per_item} of an item"
            )
        issue = availability_issue(variant, wanted)
        if issue:
            raise BadRequestException(issue)

        await self.repo.add_quantity(
            user.id, variant.id, payload.quantity, cap=settings.max_quantity_per_item
        )
        return await self.get_cart(user)

    async def update_item(
        self, user: User, item_id: uuid.UUID, payload: CartItemUpdatePayloadSchema
    ) -> CartResponseSchema:
        item = await self._get_item_or_404(user, item_id)
        issue = availability_issue(item.variant, payload.quantity)
        if issue:
            raise BadRequestException(issue)

        item.quantity = payload.quantity
        await self.repo.save()
        return await self.get_cart(user)

    async def remove_item(self, user: User, item_id: uuid.UUID) -> CartResponseSchema:
        await self.repo.delete_item(await self._get_item_or_404(user, item_id))
        return await self.get_cart(user)

    async def clear(self, user: User) -> None:
        await self.repo.clear(user.id)
