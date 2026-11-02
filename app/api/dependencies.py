import uuid

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ForbiddenException, UnauthorizedException
from app.core.security import decode_access_token
from app.database.redis import get_redis
from app.database.session import get_db
from app.model.user_model import User, UserRole
from app.repository.auth import AuthRepository

bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> User:
    if credentials is None:
        raise UnauthorizedException("Not authenticated")

    payload = decode_access_token(credentials.credentials)

    try:
        user_id = uuid.UUID(payload["sub"])
    except (KeyError, ValueError):
        raise UnauthorizedException("Invalid access token", code="TOKEN_INVALID")

    user = await AuthRepository(db, redis).get_user_by_id(user_id)
    if user is None or not user.is_active:
        raise UnauthorizedException("Account is disabled", code="ACCOUNT_DISABLED")
    return user


async def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != UserRole.ADMIN:
        raise ForbiddenException("Admin access required")
    return user
