from fastapi import APIRouter, Depends
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user
from app.api.responses import ok
from app.database.redis import get_redis
from app.database.session import get_db
from app.model.user_model import User
from app.schema.auth_schema import (
    AuthResponseSchema,
    ChangePasswordPayloadSchema,
    ForgotPasswordPayloadSchema,
    ForgotPasswordRequestSchema,
    LoginPayloadSchema,
    LogoutPayloadSchema,
    RefreshTokenPayloadSchema,
    ResetPasswordPayloadSchema,
    SignUpPayloadSchema,
    TokenResponseSchema,
)
from app.schema.response_schema import ResponseSchema
from app.services.auth import AuthService

auth_route = APIRouter(
    prefix="/auth",
    tags=["Authentication"],
)


def get_auth_service(
    db: AsyncSession = Depends(get_db), redis: Redis = Depends(get_redis)
) -> AuthService:
    return AuthService(db, redis=redis)


@auth_route.post("/sign-up", response_model=ResponseSchema[AuthResponseSchema])
async def sign_up(
    payload: SignUpPayloadSchema, service: AuthService = Depends(get_auth_service)
):
    return ok("Registration successful", await service.sign_up(payload))


@auth_route.post("/login", response_model=ResponseSchema[AuthResponseSchema])
async def login(
    payload: LoginPayloadSchema, service: AuthService = Depends(get_auth_service)
):
    return ok("Login successful", await service.login(payload))


@auth_route.post("/refresh", response_model=ResponseSchema[TokenResponseSchema])
async def refresh(
    payload: RefreshTokenPayloadSchema,
    service: AuthService = Depends(get_auth_service),
):
    return ok("Token refreshed", await service.refresh(payload))


@auth_route.post("/logout", response_model=ResponseSchema[None])
async def logout(
    payload: LogoutPayloadSchema,
    user: User = Depends(get_current_user),
    service: AuthService = Depends(get_auth_service),
):
    await service.logout(payload, user)
    return ok("Logged out")


# Forgot password: 1) request OTP  2) verify OTP  3) reset password


@auth_route.post("/forgot-password", response_model=ResponseSchema[None])
async def forgot_password(
    payload: ForgotPasswordRequestSchema,
    service: AuthService = Depends(get_auth_service),
):
    await service.forgot_password_request(payload)
    return ok("If this email is registered, an OTP has been sent")


@auth_route.post("/forgot-password/verify", response_model=ResponseSchema[None])
async def forgot_password_verify(
    payload: ForgotPasswordPayloadSchema,
    service: AuthService = Depends(get_auth_service),
):
    await service.forgot_password_verify(payload)
    return ok("OTP verified")


@auth_route.post("/reset-password", response_model=ResponseSchema[None])
async def reset_password(
    payload: ResetPasswordPayloadSchema,
    service: AuthService = Depends(get_auth_service),
):
    await service.reset_password(payload)
    return ok("Password reset successful")


@auth_route.post("/change-password", response_model=ResponseSchema[None])
async def change_password(
    payload: ChangePasswordPayloadSchema,
    user: User = Depends(get_current_user),
    service: AuthService = Depends(get_auth_service),
):
    await service.change_password(payload, user)
    return ok("Password changed successfully")
