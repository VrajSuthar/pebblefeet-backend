import uuid

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    BadRequestException,
    ConflictException,
    NotFoundException,
)
from app.core.security import verify_password
from app.model.user_model import User, UserAddress, UserRole
from app.repository.user import UserRepository
from app.schema.common_schema import PageSchema
from app.schema.user_schema import (
    INDIA,
    PIN_CODE_PATTERN,
    AddressCreatePayloadSchema,
    AddressResponseSchema,
    AddressUpdatePayloadSchema,
    AdminUserQuerySchema,
    AdminUserSchema,
    AdminUserUpdatePayloadSchema,
    DeleteAccountPayloadSchema,
    UserProfileSchema,
    UserUpdatePayloadSchema,
)


def _snapshot(user: User) -> User:
    # Just the fields that make up the cache keys
    return User(id=user.id, email=user.email, phone_number=user.phone_number)


class UserService:
    def __init__(self, db: AsyncSession, redis: Redis):
        self.repo = UserRepository(db, redis=redis)

    async def _load(self, user_id: uuid.UUID) -> User:
        user = await self.repo.get_user_for_update(user_id)
        if user is None:
            raise NotFoundException("User not found")
        return user

    # ------------------------------ Profile ------------------------------

    async def get_profile(self, user: User) -> UserProfileSchema:
        return UserProfileSchema.model_validate(await self._load(user.id))

    async def update_profile(
        self, user: User, payload: UserUpdatePayloadSchema
    ) -> UserProfileSchema:
        db_user = await self._load(user.id)
        changes = payload.changes()

        if "phone_number" in changes and await self.repo.phone_taken(
            changes["phone_number"], exclude_id=db_user.id
        ):
            raise ConflictException("This phone number is already registered")

        previous = _snapshot(db_user)
        for field, value in changes.items():
            setattr(db_user, field, value)
        db_user = await self.repo.save_user(db_user, previous=previous)
        return UserProfileSchema.model_validate(db_user)

    async def delete_account(
        self, user: User, payload: DeleteAccountPayloadSchema
    ) -> None:
        # Deactivated, not deleted: orders are financial records that must
        # keep pointing at a user (FK is RESTRICT). Logs out every device.
        db_user = await self._load(user.id)
        if not verify_password(payload.password, db_user.password_hash):
            raise BadRequestException("Password is incorrect")
        await self.repo.deactivate_user(db_user)

    # ------------------------------ Addresses ------------------------------

    async def _get_address_or_404(
        self, user_id: uuid.UUID, address_id: uuid.UUID
    ) -> UserAddress:
        address = await self.repo.get_address(user_id, address_id)
        if address is None:
            raise NotFoundException("Address not found")
        return address

    async def list_addresses(self, user: User) -> list[AddressResponseSchema]:
        addresses = await self.repo.list_addresses(user.id)
        return [AddressResponseSchema.model_validate(a) for a in addresses]

    async def get_address(
        self, user: User, address_id: uuid.UUID
    ) -> AddressResponseSchema:
        address = await self._get_address_or_404(user.id, address_id)
        return AddressResponseSchema.model_validate(address)

    async def create_address(
        self, user: User, payload: AddressCreatePayloadSchema
    ) -> AddressResponseSchema:
        # The first address is always the default one
        is_default = payload.is_default or await self.repo.count_addresses(user.id) == 0
        if is_default:
            await self.repo.clear_default_address(user.id)

        address = await self.repo.create_address(
            UserAddress(
                user_id=user.id, **payload.model_dump(exclude={"is_default"}), is_default=is_default
            )
        )
        return AddressResponseSchema.model_validate(address)

    async def update_address(
        self, user: User, address_id: uuid.UUID, payload: AddressUpdatePayloadSchema
    ) -> AddressResponseSchema:
        address = await self._get_address_or_404(user.id, address_id)
        changes = payload.changes()

        # Validate the PIN against the final country, which may come from the row
        country = changes.get("country", address.country)
        postal_code = changes.get("postal_code", address.postal_code)
        if country == INDIA and not PIN_CODE_PATTERN.match(postal_code):
            raise BadRequestException("Enter a valid 6-digit PIN code")

        if changes.get("is_default") is True:
            await self.repo.clear_default_address(user.id)
        elif changes.get("is_default") is False and address.is_default:
            # Exactly one default at all times; pick another one to make default instead
            changes.pop("is_default")

        for field, value in changes.items():
            setattr(address, field, value)
        address = await self.repo.save_address(address)
        return AddressResponseSchema.model_validate(address)

    async def delete_address(self, user: User, address_id: uuid.UUID) -> None:
        # Past orders keep their own copy of the address, so this is safe
        address = await self._get_address_or_404(user.id, address_id)
        was_default = address.is_default
        await self.repo.delete_address(address)

        if was_default:
            replacement = await self.repo.latest_address(user.id)
            if replacement is not None:
                replacement.is_default = True
        await self.repo.commit()

    # ------------------------------ Admin ------------------------------

    async def admin_list_users(
        self, query: AdminUserQuerySchema
    ) -> PageSchema[AdminUserSchema]:
        users, total = await self.repo.list_users(query)
        return PageSchema[AdminUserSchema](
            items=[AdminUserSchema.model_validate(u) for u in users],
            total=total,
            page=query.page,
            page_size=query.page_size,
        )

    async def admin_get_user(self, user_id: uuid.UUID) -> AdminUserSchema:
        return AdminUserSchema.model_validate(await self._load(user_id))

    async def admin_update_user(
        self, admin: User, user_id: uuid.UUID, payload: AdminUserUpdatePayloadSchema
    ) -> AdminUserSchema:
        target = await self._load(user_id)
        changes = payload.changes()

        if target.id == admin.id and (
            changes.get("is_active") is False or changes.get("role") == UserRole.CUSTOMER
        ):
            raise BadRequestException("You cannot disable or demote your own account")

        if changes.get("is_active") is False:
            await self.repo.deactivate_user(target)
            changes.pop("is_active")
        for field, value in changes.items():
            setattr(target, field, value)
        target = await self.repo.save_user(target)
        return AdminUserSchema.model_validate(target)
