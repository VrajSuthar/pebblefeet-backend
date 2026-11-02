import json
import uuid
from datetime import datetime
from typing import cast

from redis.asyncio import Redis
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.model.refresh_token_model import RefreshToken
from app.model.user_model import User, UserRole

USER_CACHE_TTL_SECONDS = 900


class AuthRepository:
    def __init__(self, db: AsyncSession, redis: Redis):
        self.db = db
        self.redis = redis

    # ------------------------------ Users ------------------------------
    # Reads go Redis first, then the database (cache-aside). Every write
    # invalidates the cached entries so a read never serves stale data.

    @staticmethod
    def _user_key(user_id) -> str:
        return f"user:id:{user_id}"

    @staticmethod
    def _user_email_key(email: str) -> str:
        return f"user:email:{email}"

    @staticmethod
    def _user_phone_key(phone: str) -> str:
        return f"user:phone:{phone}"

    @staticmethod
    def _dump_user(user: User) -> str:
        return json.dumps(
            {
                "id": str(user.id),
                "email": user.email,
                "password_hash": user.password_hash,
                "first_name": user.first_name,
                "last_name": user.last_name,
                "phone_number": user.phone_number,
                "role": user.role.value,
                "is_active": user.is_active,
                "created_at": user.created_at.isoformat(),
                "updated_at": user.updated_at.isoformat(),
            }
        )

    @staticmethod
    def _load_user(raw: str) -> User:
        # Detached instance: fine for reads, never attach it to a session.
        data = json.loads(raw)
        return User(
            id=uuid.UUID(data["id"]),
            email=data["email"],
            password_hash=data["password_hash"],
            first_name=data["first_name"],
            last_name=data["last_name"],
            phone_number=data["phone_number"],
            role=UserRole(data["role"]),
            is_active=data["is_active"],
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
        )

    async def _cache_user(self, user: User) -> None:
        async with self.redis.pipeline(transaction=True) as pipe:
            pipe.set(
                self._user_key(user.id),
                self._dump_user(user),
                ex=USER_CACHE_TTL_SECONDS,
            )
            pipe.set(
                self._user_email_key(user.email),
                str(user.id),
                ex=USER_CACHE_TTL_SECONDS,
            )
            pipe.set(
                self._user_phone_key(user.phone_number),
                str(user.id),
                ex=USER_CACHE_TTL_SECONDS,
            )
            await pipe.execute()

    async def invalidate_user(self, user: User) -> None:
        """Drop cached copies; call with the user's values *before* changing
        email or phone so the old lookup keys are removed too."""
        await self._invalidate_user(user)

    async def _invalidate_user(self, user: User) -> None:
        await self.redis.delete(
            self._user_key(user.id),
            self._user_email_key(user.email),
            self._user_phone_key(user.phone_number),
        )

    async def get_user_by_id(self, user_id) -> User | None:
        raw = cast(str | None, await self.redis.get(self._user_key(user_id)))
        if raw is not None:
            return self._load_user(raw)

        user = await self.db.get(User, user_id)
        if user is not None:
            await self._cache_user(user)
        return user

    async def get_user_by_email(self, email: str) -> User | None:
        user_id = cast(str | None, await self.redis.get(self._user_email_key(email)))
        if user_id is not None:
            user = await self.get_user_by_id(uuid.UUID(user_id))
            if user is not None:
                return user

        result = await self.db.execute(select(User).where(User.email == email))
        user = result.scalars().first()
        if user is not None:
            await self._cache_user(user)
        return user

    async def get_user_by_phone(self, phone: str) -> User | None:
        user_id = cast(str | None, await self.redis.get(self._user_phone_key(phone)))
        if user_id is not None:
            user = await self.get_user_by_id(uuid.UUID(user_id))
            if user is not None:
                return user

        result = await self.db.execute(select(User).where(User.phone_number == phone))
        user = result.scalars().first()
        if user is not None:
            await self._cache_user(user)
        return user

    async def create_user(self, user: User) -> User:
        self.db.add(user)
        await self.db.commit()
        await self.db.refresh(user)
        await self._cache_user(user)
        return user

    async def touch_last_login(self, user_id) -> None:
        # Not cached, so no cache invalidation needed
        await self.db.execute(
            update(User).where(User.id == user_id).values(last_login_at=func.now())
        )
        await self.db.commit()

    async def set_password(self, user: User, password_hash: str) -> None:
        # `user` may be a detached copy from the cache, so update the DB row.
        db_user = await self.db.get(User, user.id)
        if db_user is None:
            return
        db_user.password_hash = password_hash
        await self.revoke_all_refresh_tokens(db_user.id, commit=False)
        await self.db.commit()
        await self._invalidate_user(db_user)

    # --------------------------- Refresh tokens ---------------------------

    async def add_refresh_token(
        self,
        user_id,
        token_hash: str,
        device_name: str,
        player_id: str,
        expires_at: datetime,
    ) -> RefreshToken:
        record = RefreshToken(
            user_id=user_id,
            token_hash=token_hash,
            device_name=device_name,
            player_id=player_id,
            expires_at=expires_at,
        )
        self.db.add(record)
        await self.db.commit()
        return record

    async def get_refresh_token(self, token_hash: str) -> RefreshToken | None:
        result = await self.db.execute(
            select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        )
        return result.scalars().first()

    async def revoke_refresh_token(self, record: RefreshToken) -> None:
        record.is_revoked = True
        await self.db.commit()

    async def revoke_all_refresh_tokens(self, user_id, commit: bool = True) -> None:
        await self.db.execute(
            update(RefreshToken)
            .where(RefreshToken.user_id == user_id, RefreshToken.is_revoked.is_(False))
            .values(is_revoked=True)
        )
        if commit:
            await self.db.commit()

    # ------------------------ Password reset OTP (Redis) ------------------------

    @staticmethod
    def _otp_key(email: str) -> str:
        return f"pwreset:otp:{email}"

    @staticmethod
    def _attempts_key(email: str) -> str:
        return f"pwreset:attempts:{email}"

    async def store_reset_otp(self, email: str, otp_hash: str, ttl: int) -> None:
        async with self.redis.pipeline(transaction=True) as pipe:
            pipe.set(self._otp_key(email), otp_hash, ex=ttl)
            pipe.set(self._attempts_key(email), "0", ex=ttl)
            await pipe.execute()

    async def get_reset_otp(self, email: str) -> str | None:
        # client is created with decode_responses=True, so values are str
        return cast(str | None, await self.redis.get(self._otp_key(email)))

    async def get_reset_attempts(self, email: str) -> int:
        return int(await self.redis.get(self._attempts_key(email)) or 0)

    async def incr_reset_attempts(self, email: str) -> None:
        await self.redis.incr(self._attempts_key(email))

    async def clear_reset_otp(self, email: str) -> None:
        await self.redis.delete(self._otp_key(email), self._attempts_key(email))
