import uuid
from decimal import Decimal

from pydantic import BaseModel, Field

from app.core.settings import settings


class CartItemAddPayloadSchema(BaseModel):
    variant_id: uuid.UUID
    # Added to whatever is already in the cart for this variant
    quantity: int = Field(default=1, ge=1, le=settings.max_quantity_per_item)


class CartItemUpdatePayloadSchema(BaseModel):
    # The new total for this line
    quantity: int = Field(ge=1, le=settings.max_quantity_per_item)


class CartItemResponseSchema(BaseModel):
    id: uuid.UUID
    variant_id: uuid.UUID
    product_id: uuid.UUID
    product_name: str
    product_slug: str
    variant_name: str
    sku: str
    image_url: str | None
    unit_price: Decimal
    mrp: Decimal | None
    quantity: int
    line_total: Decimal
    available_stock: int
    # False when the item cannot be bought as is; `issue` says why
    is_available: bool
    issue: str | None


class CartResponseSchema(BaseModel):
    items: list[CartItemResponseSchema]
    item_count: int
    subtotal: Decimal
    shipping_fee: Decimal
    total: Decimal
    # How much more to add for free shipping; 0 when already free
    amount_for_free_shipping: Decimal
    # Checkout is blocked until every item is available
    has_issues: bool
