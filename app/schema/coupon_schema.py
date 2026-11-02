import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.model.coupon_model import DiscountType
from app.schema.common_schema import PageQuerySchema, PartialUpdateSchema

CODE_PATTERN = r"^[A-Z0-9_-]{3,50}$"


def _upper_code(value: str | None) -> str | None:
    return None if value is None else value.strip().upper()


def _check_rules(
    discount_type: DiscountType | None,
    discount_value: Decimal | None,
    valid_from: datetime | None,
    valid_until: datetime | None,
) -> None:
    if (
        discount_type == DiscountType.PERCENTAGE
        and discount_value is not None
        and discount_value > 100
    ):
        raise ValueError("A percentage discount cannot be more than 100")
    if valid_from and valid_until and valid_until <= valid_from:
        raise ValueError("valid_until must be after valid_from")


class CouponResponseSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    description: str | None
    discount_type: DiscountType
    discount_value: Decimal
    max_discount_amount: Decimal | None
    min_order_amount: Decimal
    usage_limit: int | None
    per_user_limit: int | None
    used_count: int
    valid_from: datetime
    valid_until: datetime | None
    is_active: bool


class CouponCreatePayloadSchema(BaseModel):
    # Stored upper-case; customers can type it in any case
    code: str = Field(pattern=CODE_PATTERN)
    description: str | None = Field(default=None, max_length=255)
    discount_type: DiscountType
    discount_value: Decimal = Field(gt=0, max_digits=10, decimal_places=2)
    # Caps a percentage coupon, e.g. 20% off up to ₹200
    max_discount_amount: Decimal | None = Field(
        default=None, gt=0, max_digits=10, decimal_places=2
    )
    min_order_amount: Decimal = Field(default=Decimal("0"), ge=0, max_digits=10, decimal_places=2)
    # Null means unlimited
    usage_limit: int | None = Field(default=None, ge=1)
    per_user_limit: int | None = Field(default=1, ge=1)
    valid_from: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    valid_until: datetime | None = None
    is_active: bool = True

    _clean_code = field_validator("code", mode="before")(_upper_code)

    @model_validator(mode="after")
    def check_rules(self) -> Self:
        _check_rules(self.discount_type, self.discount_value, self.valid_from, self.valid_until)
        return self


class CouponUpdatePayloadSchema(PartialUpdateSchema):
    non_nullable = frozenset(
        {"code", "discount_type", "discount_value", "min_order_amount", "valid_from", "is_active"}
    )

    code: str | None = Field(default=None, pattern=CODE_PATTERN)
    description: str | None = Field(default=None, max_length=255)
    discount_type: DiscountType | None = None
    discount_value: Decimal | None = Field(default=None, gt=0, max_digits=10, decimal_places=2)
    max_discount_amount: Decimal | None = Field(
        default=None, gt=0, max_digits=10, decimal_places=2
    )
    min_order_amount: Decimal | None = Field(default=None, ge=0, max_digits=10, decimal_places=2)
    usage_limit: int | None = Field(default=None, ge=1)
    per_user_limit: int | None = Field(default=None, ge=1)
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    is_active: bool | None = None

    _clean_code = field_validator("code", mode="before")(_upper_code)


class AdminCouponQuerySchema(PageQuerySchema):
    search: str | None = Field(default=None, max_length=50)
    is_active: bool | None = None
