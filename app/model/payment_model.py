import uuid
from decimal import Decimal
from enum import Enum
from typing import TYPE_CHECKING, Any

from sqlalchemy import Enum as SQLEnum, ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.model.base_model import Base, TimestampMixin

if TYPE_CHECKING:
    from app.model.order_model import Order


class TransactionStatus(str, Enum):
    CREATED = "created"  # Razorpay order created, checkout opened
    CAPTURED = "captured"
    FAILED = "failed"
    REFUNDED = "refunded"


class Payment(Base, TimestampMixin):
    """One payment attempt. An order can have several (retries after failure)."""

    __tablename__ = "payments"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        index=True,
    )
    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("orders.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="INR", nullable=False)
    status: Mapped[TransactionStatus] = mapped_column(
        SQLEnum(TransactionStatus, name="transaction_status"),
        default=TransactionStatus.CREATED,
        nullable=False,
    )

    # Razorpay Payment Integration Details
    razorpay_order_id: Mapped[str] = mapped_column(
        String(100), unique=True, index=True, nullable=False
    )
    razorpay_payment_id: Mapped[str | None] = mapped_column(
        String(100), unique=True, nullable=True
    )
    razorpay_signature: Mapped[str | None] = mapped_column(String(255), nullable=True)
    razorpay_refund_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    method: Mapped[str | None] = mapped_column(
        String(30), nullable=True
    )  # upi / card / netbanking / wallet
    failure_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Raw webhook/verification payload, kept for debugging and disputes
    gateway_response: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True
    )

    # Relationships
    order: Mapped["Order"] = relationship("Order", back_populates="payments")
