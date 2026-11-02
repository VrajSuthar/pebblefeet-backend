import uuid
from datetime import datetime

from pydantic import BaseModel

from app.schema.product_schema import ProductListItemSchema


class WishlistAddPayloadSchema(BaseModel):
    product_id: uuid.UUID


class WishlistItemSchema(BaseModel):
    product: ProductListItemSchema
    added_at: datetime
