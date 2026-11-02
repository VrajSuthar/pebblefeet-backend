import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user
from app.api.responses import ok
from app.database.session import get_db
from app.model.user_model import User
from app.schema.response_schema import ResponseSchema
from app.schema.wishlist_schema import WishlistAddPayloadSchema, WishlistItemSchema
from app.services.wishlist import WishlistService

# Every route here needs a valid access token. FastAPI runs get_current_user
# once per request, so routes that also take `user` don't repeat the lookup.
wishlist_route = APIRouter(
    prefix="/wishlist",
    tags=["Wishlist"],
    dependencies=[Depends(get_current_user)],
)


def get_wishlist_service(db: AsyncSession = Depends(get_db)) -> WishlistService:
    return WishlistService(db)


@wishlist_route.get("", response_model=ResponseSchema[list[WishlistItemSchema]])
async def list_wishlist(
    user: User = Depends(get_current_user),
    service: WishlistService = Depends(get_wishlist_service),
):
    return ok("Wishlist fetched", await service.list_items(user))


@wishlist_route.post("", response_model=ResponseSchema[list[WishlistItemSchema]])
async def add_to_wishlist(
    payload: WishlistAddPayloadSchema,
    user: User = Depends(get_current_user),
    service: WishlistService = Depends(get_wishlist_service),
):
    return ok("Added to wishlist", await service.add(user, payload))


@wishlist_route.delete(
    "/{product_id}", response_model=ResponseSchema[list[WishlistItemSchema]]
)
async def remove_from_wishlist(
    product_id: uuid.UUID,
    user: User = Depends(get_current_user),
    service: WishlistService = Depends(get_wishlist_service),
):
    return ok("Removed from wishlist", await service.remove(user, product_id))
