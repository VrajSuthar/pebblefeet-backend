import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user
from app.api.responses import created, ok
from app.database.session import get_db
from app.model.user_model import User
from app.schema.response_schema import ResponseSchema
from app.schema.review_schema import (
    ProductReviewsSchema,
    ReviewCreatePayloadSchema,
    ReviewQuerySchema,
    ReviewResponseSchema,
    ReviewUpdatePayloadSchema,
)
from app.services.review import ReviewService

review_route = APIRouter(
    prefix="/reviews",
    tags=["Reviews"],
    dependencies=[Depends(get_current_user)],
)


def get_review_service(db: AsyncSession = Depends(get_db)) -> ReviewService:
    return ReviewService(db)


@review_route.get(
    "/product/{product_id}", response_model=ResponseSchema[ProductReviewsSchema]
)
async def list_product_reviews(
    product_id: uuid.UUID,
    query: ReviewQuerySchema = Query(),
    service: ReviewService = Depends(get_review_service),
):
    return ok("Reviews fetched", await service.list_for_product(product_id, query))


@review_route.post("", response_model=ResponseSchema[ReviewResponseSchema], status_code=201)
async def create_review(
    payload: ReviewCreatePayloadSchema,
    user: User = Depends(get_current_user),
    service: ReviewService = Depends(get_review_service),
):
    return created("Review added", await service.create(user, payload))


@review_route.patch("/{review_id}", response_model=ResponseSchema[ReviewResponseSchema])
async def update_review(
    review_id: uuid.UUID,
    payload: ReviewUpdatePayloadSchema,
    user: User = Depends(get_current_user),
    service: ReviewService = Depends(get_review_service),
):
    return ok("Review updated", await service.update(user, review_id, payload))


@review_route.delete("/{review_id}", response_model=ResponseSchema[None])
async def delete_review(
    review_id: uuid.UUID,
    user: User = Depends(get_current_user),
    service: ReviewService = Depends(get_review_service),
):
    await service.delete(user, review_id)
    return ok("Review deleted")
