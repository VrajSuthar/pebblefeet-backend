import uuid
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictException, ForbiddenException, NotFoundException
from app.model.review_model import Review
from app.model.user_model import User, UserRole
from app.repository.order import OrderRepository
from app.repository.review import ReviewRepository
from app.schema.common_schema import PageSchema
from app.schema.review_schema import (
    AdminReviewModeratePayloadSchema,
    AdminReviewQuerySchema,
    ProductReviewsSchema,
    RatingSummarySchema,
    ReviewCreatePayloadSchema,
    ReviewQuerySchema,
    ReviewResponseSchema,
    ReviewUpdatePayloadSchema,
)


def to_review_response(review: Review) -> ReviewResponseSchema:
    user = review.user
    return ReviewResponseSchema(
        id=review.id,
        product_id=review.product_id,
        reviewer_name=f"{user.first_name} {user.last_name[:1]}.".strip(),
        rating=review.rating,
        title=review.title,
        comment=review.comment,
        is_verified_purchase=review.is_verified_purchase,
        is_approved=review.is_approved,
        created_at=review.created_at,
        updated_at=review.updated_at,
    )


class ReviewService:
    def __init__(self, db: AsyncSession):
        self.repo = ReviewRepository(db)
        self.order_repo = OrderRepository(db)

    async def _get_or_404(self, review_id: uuid.UUID) -> Review:
        review = await self.repo.get(review_id)
        if review is None:
            raise NotFoundException("Review not found")
        return review

    async def list_for_product(
        self, product_id: uuid.UUID, query: ReviewQuerySchema
    ) -> ProductReviewsSchema:
        reviews, total = await self.repo.list_for_product(product_id, query)
        distribution = await self.repo.distribution(product_id)
        count = sum(distribution.values())
        average = (
            (Decimal(sum(r * c for r, c in distribution.items())) / count).quantize(Decimal("0.1"))
            if count
            else None
        )
        return ProductReviewsSchema(
            summary=RatingSummarySchema(
                average=average,
                count=count,
                distribution={rating: distribution.get(rating, 0) for rating in range(5, 0, -1)},
            ),
            items=[to_review_response(r) for r in reviews],
            total=total,
            page=query.page,
            page_size=query.page_size,
        )

    async def create(self, user: User, payload: ReviewCreatePayloadSchema) -> ReviewResponseSchema:
        if not await self.repo.product_is_active(payload.product_id):
            raise NotFoundException("Product not found")
        if await self.repo.get_for_user(user.id, payload.product_id):
            raise ConflictException("You have already reviewed this product; edit your review instead")

        review = await self.repo.create(
            Review(
                user_id=user.id,
                **payload.model_dump(),
                # Badge for buyers whose order with this product was delivered
                is_verified_purchase=await self.order_repo.has_delivered_purchase(
                    user.id, payload.product_id
                ),
            )
        )
        return to_review_response(review)

    async def update(
        self, user: User, review_id: uuid.UUID, payload: ReviewUpdatePayloadSchema
    ) -> ReviewResponseSchema:
        review = await self._get_or_404(review_id)
        if review.user_id != user.id:
            raise ForbiddenException("You can only edit your own review")

        for field, value in payload.changes().items():
            setattr(review, field, value)
        # Bought and received since writing the review? Earn the badge now.
        if not review.is_verified_purchase:
            review.is_verified_purchase = await self.order_repo.has_delivered_purchase(
                user.id, review.product_id
            )
        return to_review_response(await self.repo.save(review))

    async def delete(self, user: User, review_id: uuid.UUID) -> None:
        review = await self._get_or_404(review_id)
        if review.user_id != user.id and user.role != UserRole.ADMIN:
            raise ForbiddenException("You can only delete your own review")
        await self.repo.delete(review)

    # ------------------------------ Admin ------------------------------

    async def admin_list(self, query: AdminReviewQuerySchema) -> PageSchema[ReviewResponseSchema]:
        reviews, total = await self.repo.admin_list(query)
        return PageSchema[ReviewResponseSchema](
            items=[to_review_response(r) for r in reviews],
            total=total,
            page=query.page,
            page_size=query.page_size,
        )

    async def moderate(
        self, review_id: uuid.UUID, payload: AdminReviewModeratePayloadSchema
    ) -> ReviewResponseSchema:
        # Hidden reviews stay in the database but drop out of listings and ratings
        review = await self._get_or_404(review_id)
        review.is_approved = payload.is_approved
        return to_review_response(await self.repo.save(review))
