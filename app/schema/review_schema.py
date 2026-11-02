import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field, field_validator

from app.schema.common_schema import PageQuerySchema, PartialUpdateSchema


def _strip_or_none(value: str | None) -> str | None:
    # Blank title/comment is stored as null
    if value is None:
        return None
    return value.strip() or None


class ReviewCreatePayloadSchema(BaseModel):
    product_id: uuid.UUID
    rating: int = Field(ge=1, le=5)
    title: str | None = Field(default=None, max_length=150)
    comment: str | None = Field(default=None, max_length=2000)

    _clean_text = field_validator("title", "comment")(_strip_or_none)


class ReviewUpdatePayloadSchema(PartialUpdateSchema):
    non_nullable = frozenset({"rating"})

    rating: int | None = Field(default=None, ge=1, le=5)
    title: str | None = Field(default=None, max_length=150)
    comment: str | None = Field(default=None, max_length=2000)

    _clean_text = field_validator("title", "comment")(_strip_or_none)


class ReviewResponseSchema(BaseModel):
    id: uuid.UUID
    product_id: uuid.UUID
    # First name + last initial, e.g. "Priya S."; full names stay private
    reviewer_name: str
    rating: int
    title: str | None
    comment: str | None
    is_verified_purchase: bool
    is_approved: bool
    created_at: datetime
    updated_at: datetime


class RatingSummarySchema(BaseModel):
    average: Decimal | None
    count: int
    # {"5": 12, "4": 3, ...}
    distribution: dict[int, int]


class ProductReviewsSchema(BaseModel):
    summary: RatingSummarySchema
    items: list[ReviewResponseSchema]
    total: int
    page: int
    page_size: int


class ReviewQuerySchema(PageQuerySchema):
    rating: int | None = Field(default=None, ge=1, le=5)


class AdminReviewQuerySchema(PageQuerySchema):
    product_id: uuid.UUID | None = None
    is_approved: bool | None = None
    rating: int | None = Field(default=None, ge=1, le=5)


class AdminReviewModeratePayloadSchema(BaseModel):
    is_approved: bool
