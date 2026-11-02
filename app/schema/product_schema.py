import re
import uuid
from decimal import Decimal
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schema.common_schema import PartialUpdateSchema

MAX_PAGE_SIZE = 50
SLUG_PATTERN = r"^[a-z0-9]+(?:-[a-z0-9]+)*$"
GST_MAX = Decimal("28")


def _strip_required(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("Cannot be blank")
    return value


def _strip_optional(value: str | None) -> str | None:
    return None if value is None else _strip_required(value)


def _normalise_skin_types(values: list[str]) -> list[str]:
    cleaned = [re.sub(r"\s+", "-", v.strip().lower()) for v in values]
    return list(dict.fromkeys(v for v in cleaned if v))


# ------------------------------ Responses ------------------------------


class CategoryResponseSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    parent_id: uuid.UUID | None
    name: str
    slug: str
    description: str | None
    image_url: str | None
    sort_order: int
    is_active: bool


class ProductImageResponseSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    variant_id: uuid.UUID | None
    image_url: str
    alt_text: str | None
    sort_order: int
    is_primary: bool


class ProductVariantResponseSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    sku: str
    name: str
    weight_grams: int
    pack_quantity: int
    price: Decimal
    mrp: Decimal | None
    stock: int
    is_active: bool


class ProductListItemSchema(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    short_description: str | None
    category_id: uuid.UUID
    is_featured: bool
    min_price: Decimal | None
    mrp: Decimal | None
    in_stock: bool
    primary_image_url: str | None
    rating_average: Decimal | None = None
    review_count: int = 0


class ProductDetailSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    slug: str
    short_description: str | None
    description: str | None
    ingredients: str | None
    benefits: str | None
    how_to_use: str | None
    fragrance: str | None
    skin_types: list[str]
    is_vegan: bool
    is_handmade: bool
    shelf_life_months: int | None
    hsn_code: str
    gst_rate: Decimal
    is_featured: bool
    is_active: bool
    category: CategoryResponseSchema
    variants: list[ProductVariantResponseSchema]
    images: list[ProductImageResponseSchema]
    rating_average: Decimal | None = None
    review_count: int = 0


class ProductListQuerySchema(BaseModel):
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=MAX_PAGE_SIZE)
    category_slug: str | None = None
    skin_type: str | None = None
    search: str | None = Field(default=None, max_length=100)
    featured: bool | None = None


class ProductListResponseSchema(BaseModel):
    items: list[ProductListItemSchema]
    total: int
    page: int
    page_size: int


# ------------------------------ Categories ------------------------------


class CategoryCreatePayloadSchema(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    # Generated from the name when omitted
    slug: str | None = Field(default=None, max_length=120, pattern=SLUG_PATTERN)
    parent_id: uuid.UUID | None = None
    description: str | None = None
    image_url: str | None = Field(default=None, max_length=512)
    sort_order: int = 0
    is_active: bool = True

    _strip_name = field_validator("name")(_strip_required)


class CategoryUpdatePayloadSchema(PartialUpdateSchema):
    non_nullable = frozenset({"name", "slug", "sort_order", "is_active"})

    name: str | None = Field(default=None, min_length=1, max_length=100)
    slug: str | None = Field(default=None, max_length=120, pattern=SLUG_PATTERN)
    parent_id: uuid.UUID | None = None
    description: str | None = None
    image_url: str | None = Field(default=None, max_length=512)
    sort_order: int | None = None
    is_active: bool | None = None

    _strip_name = field_validator("name")(_strip_optional)


# ------------------------------ Variants ------------------------------


class VariantCreatePayloadSchema(BaseModel):
    sku: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=100)
    weight_grams: int = Field(gt=0)
    pack_quantity: int = Field(default=1, gt=0)
    price: Decimal = Field(ge=0, max_digits=10, decimal_places=2)
    mrp: Decimal | None = Field(default=None, ge=0, max_digits=10, decimal_places=2)
    stock: int = Field(default=0, ge=0)
    is_active: bool = True

    _strip_text = field_validator("sku", "name")(_strip_required)

    @model_validator(mode="after")
    def check_mrp(self) -> Self:
        if self.mrp is not None and self.mrp < self.price:
            raise ValueError("MRP cannot be lower than the selling price")
        return self


class VariantUpdatePayloadSchema(PartialUpdateSchema):
    non_nullable = frozenset(
        {"sku", "name", "weight_grams", "pack_quantity", "price", "stock", "is_active"}
    )

    sku: str | None = Field(default=None, min_length=1, max_length=64)
    name: str | None = Field(default=None, min_length=1, max_length=100)
    weight_grams: int | None = Field(default=None, gt=0)
    pack_quantity: int | None = Field(default=None, gt=0)
    price: Decimal | None = Field(default=None, ge=0, max_digits=10, decimal_places=2)
    mrp: Decimal | None = Field(default=None, ge=0, max_digits=10, decimal_places=2)
    stock: int | None = Field(default=None, ge=0)
    is_active: bool | None = None

    _strip_text = field_validator("sku", "name")(_strip_optional)


# ------------------------------ Images ------------------------------


class ImageCreatePayloadSchema(BaseModel):
    image_url: str = Field(min_length=1, max_length=512)
    alt_text: str | None = Field(default=None, max_length=255)
    sort_order: int = 0
    is_primary: bool = False


class ProductImageCreatePayloadSchema(ImageCreatePayloadSchema):
    # Must belong to the same product; null shows the image for every variant
    variant_id: uuid.UUID | None = None


# ------------------------------ Products ------------------------------


class ProductCreatePayloadSchema(BaseModel):
    category_id: uuid.UUID
    name: str = Field(min_length=1, max_length=255)
    # Generated from the name when omitted
    slug: str | None = Field(default=None, max_length=280, pattern=SLUG_PATTERN)
    short_description: str | None = Field(default=None, max_length=500)
    description: str | None = None
    ingredients: str | None = None
    benefits: str | None = None
    how_to_use: str | None = None
    fragrance: str | None = Field(default=None, max_length=100)
    skin_types: list[str] = Field(default_factory=list)
    is_vegan: bool = False
    is_handmade: bool = False
    shelf_life_months: int | None = Field(default=None, gt=0)
    hsn_code: str = Field(default="3401", min_length=1, max_length=10)
    gst_rate: Decimal = Field(default=Decimal("18"), ge=0, le=GST_MAX)
    is_featured: bool = False
    is_active: bool = True
    variants: list[VariantCreatePayloadSchema] = Field(default_factory=list)
    images: list[ImageCreatePayloadSchema] = Field(default_factory=list)

    _strip_name = field_validator("name")(_strip_required)
    _clean_skin_types = field_validator("skin_types")(_normalise_skin_types)

    @model_validator(mode="after")
    def check_nested(self) -> Self:
        skus = [v.sku for v in self.variants]
        if len(skus) != len(set(skus)):
            raise ValueError("Variant SKUs must be unique")
        if sum(i.is_primary for i in self.images) > 1:
            raise ValueError("Only one image can be primary")
        return self


class ProductUpdatePayloadSchema(PartialUpdateSchema):
    non_nullable = frozenset(
        {
            "category_id",
            "name",
            "slug",
            "skin_types",
            "is_vegan",
            "is_handmade",
            "hsn_code",
            "gst_rate",
            "is_featured",
            "is_active",
        }
    )

    category_id: uuid.UUID | None = None
    name: str | None = Field(default=None, min_length=1, max_length=255)
    slug: str | None = Field(default=None, max_length=280, pattern=SLUG_PATTERN)
    short_description: str | None = Field(default=None, max_length=500)
    description: str | None = None
    ingredients: str | None = None
    benefits: str | None = None
    how_to_use: str | None = None
    fragrance: str | None = Field(default=None, max_length=100)
    skin_types: list[str] | None = None
    is_vegan: bool | None = None
    is_handmade: bool | None = None
    shelf_life_months: int | None = Field(default=None, gt=0)
    hsn_code: str | None = Field(default=None, min_length=1, max_length=10)
    gst_rate: Decimal | None = Field(default=None, ge=0, le=GST_MAX)
    is_featured: bool | None = None
    is_active: bool | None = None

    _strip_name = field_validator("name")(_strip_optional)

    @field_validator("skin_types")
    @classmethod
    def clean_skin_types(cls, value: list[str] | None) -> list[str] | None:
        return None if value is None else _normalise_skin_types(value)
