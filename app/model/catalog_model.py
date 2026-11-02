import uuid
from decimal import Decimal
from typing import TYPE_CHECKING, List

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.model.base_model import Base, TimestampMixin

if TYPE_CHECKING:
    from app.model.cart_model import CartItem
    from app.model.order_model import OrderItem
    from app.model.review_model import Review
    from app.model.wishlist_model import WishlistItem


class Category(Base, TimestampMixin):
    __tablename__ = "categories"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        index=True,
    )
    # Self-reference for nesting, e.g. Bath Soaps -> Herbal -> Neem
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("categories.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    slug: Mapped[str] = mapped_column(
        String(120), unique=True, index=True, nullable=False
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    sort_order: Mapped[int] = mapped_column(default=0, nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)

    # Relationships
    parent: Mapped["Category | None"] = relationship(
        "Category", remote_side="Category.id", back_populates="children"
    )
    children: Mapped[List["Category"]] = relationship(
        "Category", back_populates="parent"
    )
    products: Mapped[List["Product"]] = relationship(
        "Product", back_populates="category"
    )


class Product(Base, TimestampMixin):
    """A soap. Price and stock live on ProductVariant (weight / pack size)."""

    __tablename__ = "products"

    __table_args__ = (
        CheckConstraint(
            "gst_rate >= 0 AND gst_rate <= 28", name="ck_product_gst_rate_range"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        index=True,
    )
    category_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("categories.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(
        String(280), unique=True, index=True, nullable=False
    )
    short_description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Soap details shown on the product page
    ingredients: Mapped[str | None] = mapped_column(Text, nullable=True)
    benefits: Mapped[str | None] = mapped_column(Text, nullable=True)
    how_to_use: Mapped[str | None] = mapped_column(Text, nullable=True)
    fragrance: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # e.g. ["oily", "dry", "sensitive", "all"]; used for filtering
    skin_types: Mapped[List[str]] = mapped_column(
        ARRAY(String(30)), default=list, server_default="{}", nullable=False
    )
    is_vegan: Mapped[bool] = mapped_column(default=False, nullable=False)
    is_handmade: Mapped[bool] = mapped_column(default=False, nullable=False)
    shelf_life_months: Mapped[int | None] = mapped_column(nullable=True)

    # Tax (India): HSN 3401 covers soaps; rate is used to build invoices
    hsn_code: Mapped[str] = mapped_column(String(10), default="3401", nullable=False)
    gst_rate: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), default=18, nullable=False
    )

    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
    is_featured: Mapped[bool] = mapped_column(default=False, nullable=False)

    # Relationships
    category: Mapped["Category"] = relationship("Category", back_populates="products")
    variants: Mapped[List["ProductVariant"]] = relationship(
        "ProductVariant", back_populates="product", cascade="all, delete-orphan"
    )
    images: Mapped[List["ProductImage"]] = relationship(
        "ProductImage",
        back_populates="product",
        cascade="all, delete-orphan",
        order_by="ProductImage.sort_order",
    )
    reviews: Mapped[List["Review"]] = relationship(
        "Review", back_populates="product", cascade="all, delete-orphan"
    )
    wishlist_items: Mapped[List["WishlistItem"]] = relationship(
        "WishlistItem", back_populates="product", cascade="all, delete-orphan"
    )


class ProductVariant(Base, TimestampMixin):
    """A sellable unit (SKU), e.g. "100g" or "Pack of 3 x 100g"."""

    __tablename__ = "product_variants"

    __table_args__ = (
        UniqueConstraint(
            "product_id", "weight_grams", "pack_quantity", name="uq_variant_weight_pack"
        ),
        CheckConstraint("stock >= 0", name="ck_variant_stock_non_negative"),
        CheckConstraint("price >= 0", name="ck_variant_price_non_negative"),
        CheckConstraint(
            "mrp IS NULL OR mrp >= price", name="ck_variant_mrp_gte_price"
        ),
        CheckConstraint("weight_grams > 0", name="ck_variant_weight_positive"),
        CheckConstraint("pack_quantity > 0", name="ck_variant_pack_positive"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        index=True,
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sku: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)  # display label
    # Weight of one bar; total shipping weight = weight_grams * pack_quantity
    weight_grams: Mapped[int] = mapped_column(nullable=False)
    pack_quantity: Mapped[int] = mapped_column(default=1, nullable=False)

    # Selling price; mrp is the struck-through "was" price (must be printed on pack)
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    mrp: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    stock: Mapped[int] = mapped_column(default=0, nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)

    # Relationships
    product: Mapped["Product"] = relationship("Product", back_populates="variants")
    cart_items: Mapped[List["CartItem"]] = relationship(
        "CartItem", back_populates="variant", cascade="all, delete-orphan"
    )
    order_items: Mapped[List["OrderItem"]] = relationship(
        "OrderItem", back_populates="variant"
    )


class ProductImage(Base, TimestampMixin):
    __tablename__ = "product_images"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        index=True,
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Optional, e.g. a dedicated photo of the 3-pack; null applies to every variant
    variant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("product_variants.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    image_url: Mapped[str] = mapped_column(String(512), nullable=False)
    alt_text: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sort_order: Mapped[int] = mapped_column(default=0, nullable=False)
    is_primary: Mapped[bool] = mapped_column(default=False, nullable=False)

    # Relationships
    product: Mapped["Product"] = relationship("Product", back_populates="images")
