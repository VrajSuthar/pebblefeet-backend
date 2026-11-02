from fastapi import APIRouter

from app.api.v1.endpoints.admin import admin_route
from app.api.v1.endpoints.auth import auth_route
from app.api.v1.endpoints.cart import cart_route
from app.api.v1.endpoints.health import health_route
from app.api.v1.endpoints.orders import order_route
from app.api.v1.endpoints.payment import payment_route
from app.api.v1.endpoints.product import product_route
from app.api.v1.endpoints.review import review_route
from app.api.v1.endpoints.user import user_route
from app.api.v1.endpoints.wishlist import wishlist_route

auht_api_router = APIRouter()

for route in (
    health_route,
    auth_route,
    user_route,
    product_route,
    review_route,
    wishlist_route,
    cart_route,
    order_route,
    payment_route,
    admin_route,
):
    auht_api_router.include_router(route)
