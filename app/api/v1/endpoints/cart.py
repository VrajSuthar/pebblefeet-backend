import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user
from app.api.responses import ok
from app.database.session import get_db
from app.model.user_model import User
from app.schema.cart_schema import (
    CartItemAddPayloadSchema,
    CartItemUpdatePayloadSchema,
    CartResponseSchema,
)
from app.schema.response_schema import ResponseSchema
from app.services.cart import CartService

# Every route here needs a valid access token. FastAPI runs get_current_user
# once per request, so routes that also take `user` don't repeat the lookup.
cart_route = APIRouter(
    prefix="/cart",
    tags=["Cart"],
    dependencies=[Depends(get_current_user)],
)


def get_cart_service(db: AsyncSession = Depends(get_db)) -> CartService:
    return CartService(db)


# Every write returns the whole updated cart so the app can re-render at once.


@cart_route.get("", response_model=ResponseSchema[CartResponseSchema])
async def get_cart(
    user: User = Depends(get_current_user),
    service: CartService = Depends(get_cart_service),
):
    return ok("Cart fetched", await service.get_cart(user))


@cart_route.post("/items", response_model=ResponseSchema[CartResponseSchema])
async def add_item(
    payload: CartItemAddPayloadSchema,
    user: User = Depends(get_current_user),
    service: CartService = Depends(get_cart_service),
):
    return ok("Added to cart", await service.add_item(user, payload))


@cart_route.patch("/items/{item_id}", response_model=ResponseSchema[CartResponseSchema])
async def update_item(
    item_id: uuid.UUID,
    payload: CartItemUpdatePayloadSchema,
    user: User = Depends(get_current_user),
    service: CartService = Depends(get_cart_service),
):
    return ok("Cart updated", await service.update_item(user, item_id, payload))


@cart_route.delete("/items/{item_id}", response_model=ResponseSchema[CartResponseSchema])
async def remove_item(
    item_id: uuid.UUID,
    user: User = Depends(get_current_user),
    service: CartService = Depends(get_cart_service),
):
    return ok("Removed from cart", await service.remove_item(user, item_id))


@cart_route.delete("", response_model=ResponseSchema[None])
async def clear_cart(
    user: User = Depends(get_current_user),
    service: CartService = Depends(get_cart_service),
):
    await service.clear(user)
    return ok("Cart cleared")
