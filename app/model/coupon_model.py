import uuid
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import TYPE_CHECKING, List

from sqlalchemy import CheckConstraint, DateTime, Enum as SQLEnum, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.model.base_model import Base, TimestampMixin

if TYPE_CHECKING:
    from app.model.order_model import Order


class DiscountType(str, Enum):
    PERCENTAGE = "percentage"
    FLAT = "flat"


class Coupon(Base, TimestampMixin):
    __tablename__ = "coupons"

    __table_args__ = (
        CheckConstraint("discount_value > 0", name="ck_coupon_value_positive"),
        CheckConstraint(
            "discount_type != 'PERCENTAGE' OR discount_value <= 100",
            name="ck_coupon_percentage_max_100",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        index=True,
    )
    code: Mapped[str] = mapped_column(
        String(50), unique=True, index=True, nullable=False
    )
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)

    discount_type: Mapped[DiscountType] = mapped_column(
        SQLEnum(DiscountType, name="discount_type"), nullable=False
    )
    discount_value: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    # Caps a percentage discount, e.g. 20% off up to ₹500
    max_discount_amount: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 2), nullable=True
    )
    min_order_amount: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), default=0, nullable=False
    )

    # Null limit means unlimited
    usage_limit: Mapped[int | None] = mapped_column(nullable=True)
    per_user_limit: Mapped[int | None] = mapped_column(default=1, nullable=True)
    used_count: Mapped[int] = mapped_column(default=0, nullable=False)

    valid_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    valid_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)

    # Relationships
    orders: Mapped[List["Order"]] = relationship("Order", back_populates="coupon")
