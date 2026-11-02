import uuid

from redis.asyncio import Redis
from sqlalchemy import exists, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.model.user_model import User, UserAddress
from app.repository.auth import AuthRepository
from app.repository.utils import LIKE_ESCAPE, contains_pattern
from app.schema.user_schema import AdminUserQuerySchema


class UserRepository:
    def __init__(self, db: AsyncSession, redis: Redis):
        self.db = db
        # Reused for the Redis user cache, which must be cleared on every write
        self.auth_repo = AuthRepository(db, redis=redis)

    # ------------------------------ Users ------------------------------

    async def get_user_for_update(self, user_id: uuid.UUID) -> User | None:
        # The user from get_current_user may be a detached cache copy, so
        # writes always go through a row loaded from the database.
        return await self.db.get(User, user_id)

    async def phone_taken(self, phone: str, exclude_id: uuid.UUID) -> bool:
        return bool(
            await self.db.scalar(
                select(
                    exists().where(User.phone_number == phone, User.id != exclude_id)
                )
            )
        )

    async def save_user(self, user: User, previous: User | None = None) -> User:
        """`previous` is a copy holding the old email/phone, so their cache
        keys get dropped as well."""
        await self.db.commit()
        await self.db.refresh(user)
        if previous is not None:
            await self.auth_repo.invalidate_user(previous)
        await self.auth_repo.invalidate_user(user)
        return user

    async def deactivate_user(self, user: User) -> None:
        user.is_active = False
        await self.auth_repo.revoke_all_refresh_tokens(user.id, commit=False)
        await self.save_user(user)

    async def list_users(self, query: AdminUserQuerySchema) -> tuple[list[User], int]:
        conditions = []
        if query.search:
            term = contains_pattern(query.search)
            conditions.append(
                or_(
                    User.email.ilike(term, escape=LIKE_ESCAPE),
                    User.phone_number.ilike(term, escape=LIKE_ESCAPE),
                    (User.first_name + " " + User.last_name).ilike(
                        term, escape=LIKE_ESCAPE
                    ),
                )
            )
        if query.role is not None:
            conditions.append(User.role == query.role)
        if query.is_active is not None:
            conditions.append(User.is_active.is_(query.is_active))

        total = await self.db.scalar(
            select(func.count()).select_from(User).where(*conditions)
        )
        result = await self.db.execute(
            select(User)
            .where(*conditions)
            .order_by(User.created_at.desc())
            .offset(query.offset)
            .limit(query.page_size)
        )
        return list(result.scalars().all()), total or 0

    # ------------------------------ Addresses ------------------------------

    async def list_addresses(self, user_id: uuid.UUID) -> list[UserAddress]:
        result = await self.db.execute(
            select(UserAddress)
            .where(UserAddress.user_id == user_id)
            .order_by(UserAddress.is_default.desc(), UserAddress.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_address(
        self, user_id: uuid.UUID, address_id: uuid.UUID
    ) -> UserAddress | None:
        # Scoped to the user so nobody can read or edit someone else's address
        result = await self.db.execute(
            select(UserAddress).where(
                UserAddress.id == address_id, UserAddress.user_id == user_id
            )
        )
        return result.scalars().first()

    async def count_addresses(self, user_id: uuid.UUID) -> int:
        return (
            await self.db.scalar(
                select(func.count()).where(UserAddress.user_id == user_id)
            )
            or 0
        )

    async def clear_default_address(self, user_id: uuid.UUID) -> None:
        # Not committed: runs in the same transaction as the new default
        await self.db.execute(
            update(UserAddress)
            .where(UserAddress.user_id == user_id)
            .values(is_default=False)
        )

    async def latest_address(self, user_id: uuid.UUID) -> UserAddress | None:
        result = await self.db.execute(
            select(UserAddress)
            .where(UserAddress.user_id == user_id)
            .order_by(UserAddress.created_at.desc())
            .limit(1)
        )
        return result.scalars().first()

    async def create_address(self, address: UserAddress) -> UserAddress:
        self.db.add(address)
        await self.db.commit()
        await self.db.refresh(address)
        return address

    async def save_address(self, address: UserAddress) -> UserAddress:
        await self.db.commit()
        await self.db.refresh(address)
        return address

    async def delete_address(self, address: UserAddress) -> None:
        await self.db.delete(address)
        await self.db.flush()

    async def commit(self) -> None:
        await self.db.commit()
