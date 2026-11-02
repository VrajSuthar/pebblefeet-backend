"""Create (or promote) the store admin from DEFAULT_ADMIN_EMAIL / DEFAULT_ADMIN_PASSWORD.

    uv run python -m app.scripts.seed_admin

Safe to run again: an existing account with that email is made admin and
re-activated; its password is left unchanged.
"""

import asyncio

from sqlalchemy import select

from app.core.security import hash_password
from app.core.settings import settings
from app.database.redis import redis_client
from app.database.session import AsyncSessionLocal, engine
from app.model.user_model import User, UserRole
from app.repository.auth import AuthRepository

# Placeholder until the admin sets a real one in their profile
ADMIN_PHONE_PLACEHOLDER = "+910000000000"


async def main() -> None:
    email = settings.default_admin_email.strip().lower()
    if not email or not settings.default_admin_password:
        raise SystemExit("Set DEFAULT_ADMIN_EMAIL and DEFAULT_ADMIN_PASSWORD in .env first")

    async with AsyncSessionLocal() as db:
        user = (await db.execute(select(User).where(User.email == email))).scalars().first()
        if user is None:
            user = User(
                email=email,
                password_hash=hash_password(settings.default_admin_password),
                first_name="Store",
                last_name="Admin",
                phone_number=ADMIN_PHONE_PLACEHOLDER,
                role=UserRole.ADMIN,
            )
            db.add(user)
            action = "Created"
        else:
            user.role = UserRole.ADMIN
            user.is_active = True
            action = "Promoted"
        await db.commit()
        await AuthRepository(db, redis_client).invalidate_user(user)
        print(f"{action} admin account {email}")

    await engine.dispose()
    await redis_client.aclose()


if __name__ == "__main__":
    asyncio.run(main())
