import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from starlette import status

from app.api.dependencies import get_current_user, require_admin
from app.api.responses import created, ok
from app.database.session import get_db
from app.schema.product_schema import (
    CategoryCreatePayloadSchema,
    CategoryResponseSchema,
    CategoryUpdatePayloadSchema,
    ProductCreatePayloadSchema,
    ProductDetailSchema,
    ProductImageCreatePayloadSchema,
    ProductImageResponseSchema,
    ProductListQuerySchema,
    ProductListResponseSchema,
    ProductUpdatePayloadSchema,
    ProductVariantResponseSchema,
    VariantCreatePayloadSchema,
    VariantUpdatePayloadSchema,
)
from app.schema.response_schema import ResponseSchema
from app.services.product import ProductService

product_route = APIRouter(
    prefix="/products",
    tags=["Products"],
    dependencies=[Depends(get_current_user)],
)

# Write endpoints are admin only; reads need any logged-in user.
ADMIN = [Depends(require_admin)]


def get_product_service(db: AsyncSession = Depends(get_db)) -> ProductService:
    return ProductService(db)


# Static paths (/categories, /variants, /images, /id) are declared before
# /{slug} so they are not swallowed by it.

# ------------------------------ Categories ------------------------------


@product_route.get(
    "/categories", response_model=ResponseSchema[list[CategoryResponseSchema]]
)
async def list_categories(service: ProductService = Depends(get_product_service)):
    return ok("Categories fetched", await service.list_categories())


@product_route.post(
    "/categories",
    response_model=ResponseSchema[CategoryResponseSchema],
    status_code=status.HTTP_201_CREATED,
    dependencies=ADMIN,
)
async def create_category(
    payload: CategoryCreatePayloadSchema,
    service: ProductService = Depends(get_product_service),
):
    return created("Category created", await service.create_category(payload))


@product_route.patch(
    "/categories/{category_id}",
    response_model=ResponseSchema[CategoryResponseSchema],
    dependencies=ADMIN,
)
async def update_category(
    category_id: uuid.UUID,
    payload: CategoryUpdatePayloadSchema,
    service: ProductService = Depends(get_product_service),
):
    return ok("Category updated", await service.update_category(category_id, payload))


@product_route.delete(
    "/categories/{category_id}",
    response_model=ResponseSchema[None],
    dependencies=ADMIN,
)
async def delete_category(
    category_id: uuid.UUID, service: ProductService = Depends(get_product_service)
):
    await service.delete_category(category_id)
    return ok("Category deleted")


# ------------------------------ Variants ------------------------------


@product_route.patch(
    "/variants/{variant_id}",
    response_model=ResponseSchema[ProductVariantResponseSchema],
    dependencies=ADMIN,
)
async def update_variant(
    variant_id: uuid.UUID,
    payload: VariantUpdatePayloadSchema,
    service: ProductService = Depends(get_product_service),
):
    return ok("Variant updated", await service.update_variant(variant_id, payload))


@product_route.delete(
    "/variants/{variant_id}",
    response_model=ResponseSchema[None],
    dependencies=ADMIN,
)
async def delete_variant(
    variant_id: uuid.UUID, service: ProductService = Depends(get_product_service)
):
    await service.delete_variant(variant_id)
    return ok("Variant deleted")


# ------------------------------ Images ------------------------------


@product_route.delete(
    "/images/{image_id}",
    response_model=ResponseSchema[None],
    dependencies=ADMIN,
)
async def delete_image(
    image_id: uuid.UUID, service: ProductService = Depends(get_product_service)
):
    await service.delete_image(image_id)
    return ok("Image deleted")


# ------------------------------ Products ------------------------------


@product_route.get("", response_model=ResponseSchema[ProductListResponseSchema])
async def list_products(
    query: ProductListQuerySchema = Query(),
    service: ProductService = Depends(get_product_service),
):
    return ok("Products fetched", await service.list_products(query))


@product_route.post(
    "",
    response_model=ResponseSchema[ProductDetailSchema],
    status_code=status.HTTP_201_CREATED,
    dependencies=ADMIN,
)
async def create_product(
    payload: ProductCreatePayloadSchema,
    service: ProductService = Depends(get_product_service),
):
    return created("Product created", await service.create_product(payload))


@product_route.get(
    "/id/{product_id}",
    response_model=ResponseSchema[ProductDetailSchema],
    dependencies=ADMIN,
)
async def get_product_admin(
    product_id: uuid.UUID, service: ProductService = Depends(get_product_service)
):
    # Unlike /{slug}, this also returns archived products and variants
    return ok("Product fetched", await service.get_product_admin(product_id))


@product_route.get("/{slug}", response_model=ResponseSchema[ProductDetailSchema])
async def get_product(
    slug: str, service: ProductService = Depends(get_product_service)
):
    return ok("Product fetched", await service.get_product(slug))


@product_route.patch(
    "/{product_id}",
    response_model=ResponseSchema[ProductDetailSchema],
    dependencies=ADMIN,
)
async def update_product(
    product_id: uuid.UUID,
    payload: ProductUpdatePayloadSchema,
    service: ProductService = Depends(get_product_service),
):
    return ok("Product updated", await service.update_product(product_id, payload))


@product_route.delete(
    "/{product_id}",
    response_model=ResponseSchema[None],
    dependencies=ADMIN,
)
async def delete_product(
    product_id: uuid.UUID, service: ProductService = Depends(get_product_service)
):
    await service.delete_product(product_id)
    return ok("Product deleted")


@product_route.post(
    "/{product_id}/variants",
    response_model=ResponseSchema[ProductVariantResponseSchema],
    status_code=status.HTTP_201_CREATED,
    dependencies=ADMIN,
)
async def create_variant(
    product_id: uuid.UUID,
    payload: VariantCreatePayloadSchema,
    service: ProductService = Depends(get_product_service),
):
    return created("Variant created", await service.create_variant(product_id, payload))


@product_route.post(
    "/{product_id}/images",
    response_model=ResponseSchema[ProductImageResponseSchema],
    status_code=status.HTTP_201_CREATED,
    dependencies=ADMIN,
)
async def add_image(
    product_id: uuid.UUID,
    payload: ProductImageCreatePayloadSchema,
    service: ProductService = Depends(get_product_service),
):
    return created("Image added", await service.add_image(product_id, payload))
