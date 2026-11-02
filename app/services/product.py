import re
import uuid
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestException, ConflictException, NotFoundException
from app.model.catalog_model import Category, Product, ProductImage, ProductVariant
from app.repository.product import ProductRepository
from app.repository.review import ReviewRepository
from app.schema.product_schema import (
    CategoryCreatePayloadSchema,
    CategoryResponseSchema,
    CategoryUpdatePayloadSchema,
    ProductCreatePayloadSchema,
    ProductDetailSchema,
    ProductImageCreatePayloadSchema,
    ProductImageResponseSchema,
    ProductListItemSchema,
    ProductListQuerySchema,
    ProductListResponseSchema,
    ProductUpdatePayloadSchema,
    ProductVariantResponseSchema,
    VariantCreatePayloadSchema,
    VariantUpdatePayloadSchema,
)


def _slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "item"


def _round_rating(average: Decimal) -> Decimal:
    return average.quantize(Decimal("0.1"))


def _check_mrp(price: Decimal, mrp: Decimal | None) -> None:
    if mrp is not None and mrp < price:
        raise BadRequestException("MRP cannot be lower than the selling price")


class ProductService:
    def __init__(self, db: AsyncSession):
        self.repo = ProductRepository(db)
        self.review_repo = ReviewRepository(db)

    # ------------------------------ Helpers ------------------------------

    async def _resolve_slug(
        self,
        model: type[Category] | type[Product],
        name: str,
        slug: str | None,
        exclude_id=None,
    ) -> str:
        # An explicit slug must be free; a generated one gets -2, -3... appended.
        if slug is not None:
            if await self.repo.slug_exists(model, slug, exclude_id):
                raise ConflictException(f"Slug '{slug}' is already in use")
            return slug

        base = _slugify(name)
        candidate, suffix = base, 2
        while await self.repo.slug_exists(model, candidate, exclude_id):
            candidate, suffix = f"{base}-{suffix}", suffix + 1
        return candidate

    async def _get_category_or_404(self, category_id: uuid.UUID) -> Category:
        category = await self.repo.get_category(category_id)
        if category is None:
            raise NotFoundException("Category not found")
        return category

    async def _get_product_or_404(self, product_id: uuid.UUID) -> Product:
        product = await self.repo.get_product_by_id(product_id)
        if product is None:
            raise NotFoundException("Product not found")
        return product

    async def _get_variant_or_404(self, variant_id: uuid.UUID) -> ProductVariant:
        variant = await self.repo.get_variant(variant_id)
        if variant is None:
            raise NotFoundException("Variant not found")
        return variant

    async def _check_parent(self, category_id, parent_id: uuid.UUID) -> None:
        # Walk up from the new parent; reaching the category itself means a cycle.
        current = await self._get_category_or_404(parent_id)
        while current is not None:
            if current.id == category_id:
                raise BadRequestException("A category cannot be nested inside itself")
            if current.parent_id is None:
                return
            current = await self.repo.get_category(current.parent_id)

    @staticmethod
    def to_list_item(
        product: Product, rating: tuple[Decimal, int] | None = None
    ) -> ProductListItemSchema:
        variants = [v for v in product.variants if v.is_active]
        cheapest = min(variants, key=lambda v: v.price, default=None)
        images = product.images
        primary = next((i for i in images if i.is_primary), images[0] if images else None)
        return ProductListItemSchema(
            id=product.id,
            name=product.name,
            slug=product.slug,
            short_description=product.short_description,
            category_id=product.category_id,
            is_featured=product.is_featured,
            min_price=cheapest.price if cheapest else None,
            mrp=cheapest.mrp if cheapest else None,
            in_stock=any(v.stock > 0 for v in variants),
            primary_image_url=primary.image_url if primary else None,
            rating_average=_round_rating(rating[0]) if rating else None,
            review_count=rating[1] if rating else 0,
        )

    async def _to_detail(self, product: Product, include_inactive: bool) -> ProductDetailSchema:
        detail = ProductDetailSchema.model_validate(product)
        if not include_inactive:
            detail.variants = [v for v in detail.variants if v.is_active]
        rating = (await self.review_repo.summaries([product.id])).get(product.id)
        if rating:
            detail.rating_average = _round_rating(rating[0])
            detail.review_count = rating[1]
        return detail

    # ------------------------------ Categories ------------------------------

    async def list_categories(self) -> list[CategoryResponseSchema]:
        categories = await self.repo.list_categories()
        return [CategoryResponseSchema.model_validate(c) for c in categories]

    async def create_category(
        self, payload: CategoryCreatePayloadSchema
    ) -> CategoryResponseSchema:
        if payload.parent_id is not None:
            await self._get_category_or_404(payload.parent_id)

        data = payload.model_dump()
        data["slug"] = await self._resolve_slug(Category, payload.name, payload.slug)
        category = await self.repo.create_category(Category(**data))
        return CategoryResponseSchema.model_validate(category)

    async def update_category(
        self, category_id: uuid.UUID, payload: CategoryUpdatePayloadSchema
    ) -> CategoryResponseSchema:
        category = await self._get_category_or_404(category_id)
        changes = payload.changes()

        if changes.get("parent_id") is not None:
            await self._check_parent(category.id, changes["parent_id"])
        if "slug" in changes:
            changes["slug"] = await self._resolve_slug(
                Category, category.name, changes["slug"], exclude_id=category.id
            )

        for field, value in changes.items():
            setattr(category, field, value)
        category = await self.repo.save_category(category)
        return CategoryResponseSchema.model_validate(category)

    async def delete_category(self, category_id: uuid.UUID) -> None:
        # Soft delete: products keep their category_id, the category just
        # stops being listed or used as a filter.
        category = await self._get_category_or_404(category_id)
        category.is_active = False
        await self.repo.save_category(category)

    # ------------------------------ Products ------------------------------

    async def list_products(
        self, query: ProductListQuerySchema
    ) -> ProductListResponseSchema:
        products, total = await self.repo.list_products(query)
        ratings = await self.review_repo.summaries([p.id for p in products])
        return ProductListResponseSchema(
            items=[self.to_list_item(p, ratings.get(p.id)) for p in products],
            total=total,
            page=query.page,
            page_size=query.page_size,
        )

    async def get_product(self, slug: str) -> ProductDetailSchema:
        product = await self.repo.get_product_by_slug(slug)
        if product is None:
            raise NotFoundException("Product not found")
        return await self._to_detail(product, include_inactive=False)

    async def get_product_admin(self, product_id: uuid.UUID) -> ProductDetailSchema:
        product = await self._get_product_or_404(product_id)
        return await self._to_detail(product, include_inactive=True)

    async def create_product(
        self, payload: ProductCreatePayloadSchema
    ) -> ProductDetailSchema:
        await self._get_category_or_404(payload.category_id)
        if payload.variants:
            taken = await self.repo.skus_taken([v.sku for v in payload.variants])
            if taken:
                raise ConflictException(f"SKU already in use: {', '.join(taken)}")

        data = payload.model_dump(exclude={"variants", "images"})
        data["slug"] = await self._resolve_slug(Product, payload.name, payload.slug)
        product = Product(
            **data,
            variants=[ProductVariant(**v.model_dump()) for v in payload.variants],
            images=[ProductImage(**i.model_dump()) for i in payload.images],
        )
        product = await self.repo.create_product(product)
        return await self._to_detail(product, include_inactive=True)

    async def update_product(
        self, product_id: uuid.UUID, payload: ProductUpdatePayloadSchema
    ) -> ProductDetailSchema:
        product = await self._get_product_or_404(product_id)
        changes = payload.changes()

        if "category_id" in changes:
            await self._get_category_or_404(changes["category_id"])
        # Renaming keeps the old slug so existing links keep working;
        # send `slug` explicitly to change it.
        if "slug" in changes:
            changes["slug"] = await self._resolve_slug(
                Product, product.name, changes["slug"], exclude_id=product.id
            )

        for field, value in changes.items():
            setattr(product, field, value)
        product = await self.repo.save_product(product)
        return await self._to_detail(product, include_inactive=True)

    async def delete_product(self, product_id: uuid.UUID) -> None:
        # Soft delete: a hard delete would cascade away reviews, wishlist
        # and cart rows. Past orders keep their own snapshot either way.
        product = await self._get_product_or_404(product_id)
        product.is_active = False
        await self.repo.save_product(product)

    # ------------------------------ Variants ------------------------------

    async def create_variant(
        self, product_id: uuid.UUID, payload: VariantCreatePayloadSchema
    ) -> ProductVariantResponseSchema:
        await self._get_product_or_404(product_id)
        if await self.repo.sku_exists(payload.sku):
            raise ConflictException(f"SKU already in use: {payload.sku}")

        variant = await self.repo.create_variant(
            ProductVariant(product_id=product_id, **payload.model_dump())
        )
        return ProductVariantResponseSchema.model_validate(variant)

    async def update_variant(
        self, variant_id: uuid.UUID, payload: VariantUpdatePayloadSchema
    ) -> ProductVariantResponseSchema:
        variant = await self._get_variant_or_404(variant_id)
        changes = payload.changes()

        if "sku" in changes and await self.repo.sku_exists(
            changes["sku"], exclude_id=variant.id
        ):
            raise ConflictException(f"SKU already in use: {changes['sku']}")
        _check_mrp(changes.get("price", variant.price), changes.get("mrp", variant.mrp))

        for field, value in changes.items():
            setattr(variant, field, value)
        variant = await self.repo.save_variant(variant)
        return ProductVariantResponseSchema.model_validate(variant)

    async def delete_variant(self, variant_id: uuid.UUID) -> None:
        # Soft delete: carts and order history still point at this row.
        variant = await self._get_variant_or_404(variant_id)
        variant.is_active = False
        await self.repo.save_variant(variant)

    # ------------------------------ Images ------------------------------

    async def add_image(
        self, product_id: uuid.UUID, payload: ProductImageCreatePayloadSchema
    ) -> ProductImageResponseSchema:
        product = await self._get_product_or_404(product_id)
        if payload.variant_id is not None and payload.variant_id not in {
            v.id for v in product.variants
        }:
            raise BadRequestException("Variant does not belong to this product")

        if payload.is_primary:
            await self.repo.clear_primary_image(product_id)
        image = await self.repo.create_image(
            ProductImage(product_id=product_id, **payload.model_dump())
        )
        return ProductImageResponseSchema.model_validate(image)

    async def delete_image(self, image_id: uuid.UUID) -> None:
        image = await self.repo.get_image(image_id)
        if image is None:
            raise NotFoundException("Image not found")
        await self.repo.delete_image(image)
