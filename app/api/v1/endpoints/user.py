import uuid

from fastapi import APIRouter, Depends
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user
from app.api.responses import created, ok
from app.database.redis import get_redis
from app.database.session import get_db
from app.model.user_model import User
from app.schema.response_schema import ResponseSchema
from app.schema.user_schema import (
    AddressCreatePayloadSchema,
    AddressResponseSchema,
    AddressUpdatePayloadSchema,
    DeleteAccountPayloadSchema,
    UserProfileSchema,
    UserUpdatePayloadSchema,
)
from app.services.user import UserService

# Every route here needs a valid access token. FastAPI runs get_current_user
# once per request, so routes that also take `user` don't repeat the lookup.
user_route = APIRouter(
    prefix="/users/me",
    tags=["User"],
    dependencies=[Depends(get_current_user)],
)


def get_user_service(
    db: AsyncSession = Depends(get_db), redis: Redis = Depends(get_redis)
) -> UserService:
    return UserService(db, redis=redis)


# ------------------------------ Profile ------------------------------


@user_route.get("", response_model=ResponseSchema[UserProfileSchema])
async def get_profile(
    user: User = Depends(get_current_user),
    service: UserService = Depends(get_user_service),
):
    return ok("Profile fetched", await service.get_profile(user))


@user_route.patch("", response_model=ResponseSchema[UserProfileSchema])
async def update_profile(
    payload: UserUpdatePayloadSchema,
    user: User = Depends(get_current_user),
    service: UserService = Depends(get_user_service),
):
    return ok("Profile updated", await service.update_profile(user, payload))


# POST, not DELETE: the password goes in a body and some clients drop DELETE bodies
@user_route.post("/delete", response_model=ResponseSchema[None])
async def delete_account(
    payload: DeleteAccountPayloadSchema,
    user: User = Depends(get_current_user),
    service: UserService = Depends(get_user_service),
):
    await service.delete_account(user, payload)
    return ok("Account deleted")


# ------------------------------ Addresses ------------------------------


@user_route.get(
    "/addresses", response_model=ResponseSchema[list[AddressResponseSchema]]
)
async def list_addresses(
    user: User = Depends(get_current_user),
    service: UserService = Depends(get_user_service),
):
    return ok("Addresses fetched", await service.list_addresses(user))


@user_route.post(
    "/addresses", response_model=ResponseSchema[AddressResponseSchema], status_code=201
)
async def create_address(
    payload: AddressCreatePayloadSchema,
    user: User = Depends(get_current_user),
    service: UserService = Depends(get_user_service),
):
    return created("Address added", await service.create_address(user, payload))


@user_route.get(
    "/addresses/{address_id}", response_model=ResponseSchema[AddressResponseSchema]
)
async def get_address(
    address_id: uuid.UUID,
    user: User = Depends(get_current_user),
    service: UserService = Depends(get_user_service),
):
    return ok("Address fetched", await service.get_address(user, address_id))


@user_route.patch(
    "/addresses/{address_id}", response_model=ResponseSchema[AddressResponseSchema]
)
async def update_address(
    address_id: uuid.UUID,
    payload: AddressUpdatePayloadSchema,
    user: User = Depends(get_current_user),
    service: UserService = Depends(get_user_service),
):
    return ok(
        "Address updated", await service.update_address(user, address_id, payload)
    )


@user_route.delete("/addresses/{address_id}", response_model=ResponseSchema[None])
async def delete_address(
    address_id: uuid.UUID,
    user: User = Depends(get_current_user),
    service: UserService = Depends(get_user_service),
):
    await service.delete_address(user, address_id)
    return ok("Address deleted")
