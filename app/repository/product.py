import uuid

from sqlalchemy import ColumnElement, exists, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import ConflictException
from app.model.catalog_model import Category, Product, ProductImage, ProductVariant
from app.repository.utils import LIKE_ESCAPE, contains_pattern
from app.schema.product_schema import ProductListQuerySchema

_DETAIL_OPTIONS = (
    selectinload(Product.category),
    selectinload(Product.variants),
    selectinload(Product.images),
)


class ProductRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def commit(self) -> None:
        # Safety net for races on unique columns (slug, sku) that slipped
        # past the service's pre-checks.
        try:
            await self.db.commit()
        except IntegrityError as exc:
            await self.db.rollback()
            raise ConflictException(
                "A record with the same slug or SKU already exists"
            ) from exc

    async def slug_exists(
        self, model: type[Category] | type[Product], slug: str, exclude_id=None
    ) -> bool:
        condition = model.slug == slug
        if exclude_id is not None:
            condition = condition & (model.id != exclude_id)
        return bool(await self.db.scalar(select(exists().where(condition))))

    # ------------------------------ Categories ------------------------------

    async def list_categories(self) -> list[Category]:
        result = await self.db.execute(
            select(Category)
            .where(Category.is_active.is_(True))
            .order_by(Category.sort_order, Category.name)
        )
        return list(result.scalars().all())

    async def get_category(self, category_id: uuid.UUID) -> Category | None:
        return await self.db.get(Category, category_id)

    async def create_category(self, category: Category) -> Category:
        self.db.add(category)
        await self.commit()
        await self.db.refresh(category)
        return category

    async def save_category(self, category: Category) -> Category:
        await self.commit()
        await self.db.refresh(category)
        return category

    # ------------------------------ Products ------------------------------

    @staticmethod
    def _filters(query: ProductListQuerySchema) -> list[ColumnElement[bool]]:
        conditions: list[ColumnElement[bool]] = [Product.is_active.is_(True)]
        if query.category_slug:
            conditions.append(
                Product.category_id.in_(
                    select(Category.id).where(
                        Category.slug == query.category_slug,
                        Category.is_active.is_(True),
                    )
                )
            )
        if query.skin_type:
            # ARRAY containment: skin_types @> ARRAY['oily']
            conditions.append(Product.skin_types.contains([query.skin_type]))
        if query.featured is not None:
            conditions.append(Product.is_featured.is_(query.featured))
        if query.search:
            conditions.append(
                Product.name.ilike(contains_pattern(query.search), escape=LIKE_ESCAPE)
            )
        return conditions

    async def list_products(
        self, query: ProductListQuerySchema
    ) -> tuple[list[Product], int]:
        conditions = self._filters(query)

        total = await self.db.scalar(
            select(func.count()).select_from(Product).where(*conditions)
        )
        result = await self.db.execute(
            select(Product)
            .where(*conditions)
            .options(selectinload(Product.variants), selectinload(Product.images))
            .order_by(Product.is_featured.desc(), Product.created_at.desc())
            .offset((query.page - 1) * query.page_size)
            .limit(query.page_size)
        )
        return list(result.scalars().all()), total or 0

    async def get_product_by_slug(self, slug: str) -> Product | None:
        result = await self.db.execute(
            select(Product)
            .where(Product.slug == slug, Product.is_active.is_(True))
            .options(*_DETAIL_OPTIONS)
        )
        return result.scalars().first()

    def _product_by_id_query(self, product_id: uuid.UUID):
        # Includes archived products; used by admin endpoints.
        # populate_existing reloads relationships changed earlier in this session.
        return (
            select(Product)
            .where(Product.id == product_id)
            .options(*_DETAIL_OPTIONS)
            .execution_options(populate_existing=True)
        )

    async def get_product_by_id(self, product_id: uuid.UUID) -> Product | None:
        result = await self.db.execute(self._product_by_id_query(product_id))
        return result.scalars().first()

    async def _reload_product(self, product_id: uuid.UUID) -> Product:
        # The row was just written, so it is guaranteed to exist
        result = await self.db.execute(self._product_by_id_query(product_id))
        return result.scalars().one()

    async def create_product(self, product: Product) -> Product:
        self.db.add(product)
        await self.commit()
        return await self._reload_product(product.id)

    async def save_product(self, product: Product) -> Product:
        await self.commit()
        return await self._reload_product(product.id)

    # ------------------------------ Variants ------------------------------

    async def get_variant(self, variant_id: uuid.UUID) -> ProductVariant | None:
        return await self.db.get(ProductVariant, variant_id)

    async def sku_exists(self, sku: str, exclude_id=None) -> bool:
        condition = ProductVariant.sku == sku
        if exclude_id is not None:
            condition = condition & (ProductVariant.id != exclude_id)
        return bool(await self.db.scalar(select(exists().where(condition))))

    async def skus_taken(self, skus: list[str]) -> list[str]:
        result = await self.db.execute(
            select(ProductVariant.sku).where(ProductVariant.sku.in_(skus))
        )
        return list(result.scalars().all())

    async def create_variant(self, variant: ProductVariant) -> ProductVariant:
        self.db.add(variant)
        await self.commit()
        await self.db.refresh(variant)
        return variant

    async def save_variant(self, variant: ProductVariant) -> ProductVariant:
        await self.commit()
        await self.db.refresh(variant)
        return variant

    # ------------------------------ Images ------------------------------

    async def get_image(self, image_id: uuid.UUID) -> ProductImage | None:
        return await self.db.get(ProductImage, image_id)

    async def clear_primary_image(self, product_id: uuid.UUID) -> None:
        # Not committed: runs in the same transaction as the new primary image
        await self.db.execute(
            update(ProductImage)
            .where(ProductImage.product_id == product_id)
            .values(is_primary=False)
        )

    async def create_image(self, image: ProductImage) -> ProductImage:
        self.db.add(image)
        await self.commit()
        await self.db.refresh(image)
        return image

    async def delete_image(self, image: ProductImage) -> None:
        await self.db.delete(image)
        await self.commit()
