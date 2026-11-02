import uuid
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.model.base_model import Base, TimestampMixin

if TYPE_CHECKING:
    from app.model.catalog_model import ProductVariant
    from app.model.user_model import User


class CartItem(Base, TimestampMixin):
    __tablename__ = "cart_items"

    # Prevents duplicate (user_id, variant_id) rows; bump quantity instead
    __table_args__ = (
        UniqueConstraint("user_id", "variant_id", name="uq_user_variant_cart"),
        CheckConstraint("quantity > 0", name="ck_cart_quantity_positive"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        index=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    variant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("product_variants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    quantity: Mapped[int] = mapped_column(default=1, nullable=False)

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="cart_items")
    variant: Mapped["ProductVariant"] = relationship(
        "ProductVariant", back_populates="cart_items"
    )
