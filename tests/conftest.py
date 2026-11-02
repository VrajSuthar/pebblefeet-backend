"""Integration fixtures.

Every test runs inside one database transaction that is rolled back at the
end (services' commits become savepoints), so the real dev database is used
but never changed. Redis keys the tests create are deleted afterwards.
"""

import uuid
from decimal import Decimal

import httpx
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, hash_password
from app.core.settings import settings
from app.database.redis import redis_client
from app.database.session import engine, get_db
from app.main import app
from app.model.catalog_model import Category, Product, ProductImage, ProductVariant
from app.model.user_model import User, UserAddress, UserRole
from app.repository.auth import AuthRepository
from app.services.razorpay_client import get_razorpay_client
from tests.fakes import FakeRazorpay

PASSWORD = "Secret123"


@pytest_asyncio.fixture(scope="session", autouse=True)
async def _dispose_engine():
    yield
    await engine.dispose()


@pytest_asyncio.fixture
async def db():
    connection = await engine.connect()
    transaction = await connection.begin()
    session = AsyncSession(
        bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
    )
    try:
        yield session
    finally:
        await session.close()
        await transaction.rollback()
        await connection.close()


@pytest.fixture
def razorpay(monkeypatch) -> FakeRazorpay:
    fake = FakeRazorpay()
    monkeypatch.setattr(settings, "razorpay_key_id", fake.key_id)
    monkeypatch.setattr(settings, "razorpay_key_secret", fake.key_secret)
    monkeypatch.setattr(settings, "razorpay_webhook_secret", fake.webhook_secret)
    return fake


@pytest_asyncio.fixture
async def client(db, razorpay):
    async def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_razorpay_client] = lambda: razorpay
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as http:
        yield http
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def make_user(db):
    created: list[User] = []

    async def factory(role: UserRole = UserRole.CUSTOMER) -> tuple[User, dict[str, str]]:
        tag = uuid.uuid4().hex[:10]
        user = User(
            email=f"{role.value}-{tag}@example.com",
            password_hash=hash_password(PASSWORD),
            first_name="Test",
            last_name=role.value.title(),
            phone_number=f"+919{uuid.uuid4().int % 10**9:09d}",
            role=role,
        )
        db.add(user)
        await db.commit()
        created.append(user)
        token = create_access_token(str(user.id), user.role.value)
        return user, {"Authorization": f"Bearer {token}"}

    yield factory
    repo = AuthRepository(db, redis_client)
    for user in created:
        await repo.invalidate_user(user)


@pytest_asyncio.fixture
async def customer(make_user):
    return await make_user()


@pytest_asyncio.fixture
async def admin(make_user):
    return await make_user(UserRole.ADMIN)


@pytest_asyncio.fixture
async def address(db, customer) -> UserAddress:
    user, _ = customer
    address = UserAddress(
        user_id=user.id,
        recipient_name="Test Customer",
        phone_number="+919876543210",
        address_line1="12 MG Road",
        city="Ahmedabad",
        state="Gujarat",
        postal_code="380001",
        is_default=True,
    )
    db.add(address)
    await db.commit()
    return address


@pytest_asyncio.fixture
async def catalog(db):
    """One soap with a ₹120 100g bar (10 in stock) and a ₹330 3-pack (2 in stock)."""
    tag = uuid.uuid4().hex[:8]
    category = Category(name=f"Herbal {tag}", slug=f"herbal-{tag}")
    product = Product(
        category=category,
        name=f"Neem Tulsi Soap {tag}",
        slug=f"neem-tulsi-{tag}",
        gst_rate=Decimal("18"),
        skin_types=["oily"],
        images=[ProductImage(image_url="https://img.test/neem.jpg", is_primary=True)],
        variants=[
            ProductVariant(
                sku=f"NT-100-{tag}", name="100g", weight_grams=100,
                price=Decimal("120.00"), mrp=Decimal("150.00"), stock=10,
            ),
            ProductVariant(
                sku=f"NT-3P-{tag}", name="Pack of 3", weight_grams=100, pack_quantity=3,
                price=Decimal("330.00"), stock=2,
            ),
        ],
    )
    db.add(product)
    await db.commit()
    bar, pack = sorted(product.variants, key=lambda v: v.price)
    return {"category": category, "product": product, "bar": bar, "pack": pack}
