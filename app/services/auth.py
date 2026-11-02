from datetime import datetime, timedelta, timezone

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    BadRequestException,
    ConflictException,
    OtpExpiredException,
    OtpInvalidException,
    UnauthorizedException,
)
from app.core.security import (
    constant_time_equals,
    create_access_token,
    generate_otp,
    generate_refresh_token,
    hash_password,
    hash_token,
    verify_password,
)
from app.core.settings import settings
from app.model.user_model import User
from app.repository.auth import AuthRepository
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
    UserResponseSchema,
)
from app.services.email_service import EmailService

OTP_TTL_SECONDS = 300
MAX_OTP_ATTEMPTS = 5
INVALID_CREDENTIALS = "Invalid email or password"


class AuthService:
    def __init__(self, db: AsyncSession, redis: Redis):
        self.repo = AuthRepository(db, redis=redis)
        self.email_service = EmailService()

    # ------------------------------ Tokens ------------------------------

    async def _issue_tokens(
        self, user: User, device_name: str, player_id: str
    ) -> TokenResponseSchema:
        refresh_token = generate_refresh_token()
        expires_at = datetime.now(timezone.utc) + timedelta(
            days=settings.refresh_token_expire_days
        )
        await self.repo.add_refresh_token(
            user_id=user.id,
            token_hash=hash_token(refresh_token),
            device_name=device_name,
            player_id=player_id,
            expires_at=expires_at,
        )
        return TokenResponseSchema(
            access_token=create_access_token(str(user.id), user.role.value),
            refresh_token=refresh_token,
            expires_in=settings.access_token_expire_minutes * 60,
        )

    # ------------------------------ Sign up ------------------------------

    async def sign_up(self, payload: SignUpPayloadSchema) -> AuthResponseSchema:
        email = payload.email.lower()

        if await self.repo.get_user_by_email(email):
            raise ConflictException("This email is already registered, please login")
        if await self.repo.get_user_by_phone(payload.phone_number):
            raise ConflictException(
                "This phone number is already registered, please login"
            )

        user = await self.repo.create_user(
            User(
                first_name=payload.first_name,
                last_name=payload.last_name,
                email=email,
                phone_number=payload.phone_number,
                password_hash=hash_password(payload.password),
            )
        )
        tokens = await self._issue_tokens(user, payload.device_name, payload.player_id)
        return AuthResponseSchema(
            **tokens.model_dump(), user=UserResponseSchema.model_validate(user)
        )

    # ------------------------------ Login ------------------------------

    async def login(self, payload: LoginPayloadSchema) -> AuthResponseSchema:
        user = await self.repo.get_user_by_email(payload.email.lower())

        # Same message for unknown email and wrong password: don't leak which exists.
        if user is None or not verify_password(payload.password, user.password_hash):
            raise UnauthorizedException(INVALID_CREDENTIALS, code="INVALID_CREDENTIALS")
        if not user.is_active:
            raise UnauthorizedException("Account is disabled", code="ACCOUNT_DISABLED")

        await self.repo.touch_last_login(user.id)
        tokens = await self._issue_tokens(user, payload.device_name, payload.player_id)
        return AuthResponseSchema(
            **tokens.model_dump(), user=UserResponseSchema.model_validate(user)
        )

    # ------------------------------ Refresh / logout ------------------------------

    async def refresh(self, payload: RefreshTokenPayloadSchema) -> TokenResponseSchema:
        record = await self.repo.get_refresh_token(hash_token(payload.refresh_token))

        if record is None:
            raise UnauthorizedException("Invalid refresh token", code="TOKEN_INVALID")

        if record.is_revoked:
            # A rotated token being replayed means it may have been stolen:
            # kill every session for this user.
            await self.repo.revoke_all_refresh_tokens(record.user_id)
            raise UnauthorizedException("Invalid refresh token", code="TOKEN_INVALID")

        if record.expires_at <= datetime.now(timezone.utc):
            raise UnauthorizedException(
                "Refresh token has expired", code="TOKEN_EXPIRED"
            )

        user = await self.repo.get_user_by_id(record.user_id)
        if user is None or not user.is_active:
            raise UnauthorizedException("Account is disabled", code="ACCOUNT_DISABLED")

        await self.repo.revoke_refresh_token(record)
        return await self._issue_tokens(user, record.device_name, record.player_id)

    async def logout(self, payload: LogoutPayloadSchema, user: User) -> None:
        record = await self.repo.get_refresh_token(hash_token(payload.refresh_token))
        # Idempotent: an unknown/foreign token is simply ignored.
        if record is not None and record.user_id == user.id:
            await self.repo.revoke_refresh_token(record)

    # ------------------------------ Forgot password ------------------------------

    async def forgot_password_request(
        self, payload: ForgotPasswordRequestSchema
    ) -> None:
        email = payload.email.lower()
        user = await self.repo.get_user_by_email(email)

        # Always respond the same way so the endpoint can't be used to find
        # out which emails are registered.
        if user is None or not user.is_active:
            return

        otp = generate_otp()
        await self.repo.store_reset_otp(email, hash_token(otp), OTP_TTL_SECONDS)
        await self.email_service.send_password_reset_otp(email, otp)

    async def _check_reset_otp(self, email: str, otp: str) -> None:
        stored = await self.repo.get_reset_otp(email)
        if stored is None:
            raise OtpExpiredException("OTP has expired, please request a new one")

        if await self.repo.get_reset_attempts(email) >= MAX_OTP_ATTEMPTS:
            await self.repo.clear_reset_otp(email)
            raise OtpInvalidException(
                "Maximum OTP attempts exceeded. Request a new OTP."
            )

        if not constant_time_equals(stored, hash_token(otp)):
            await self.repo.incr_reset_attempts(email)
            raise OtpInvalidException("Incorrect OTP")

    async def forgot_password_verify(
        self, payload: ForgotPasswordPayloadSchema
    ) -> None:
        # Checks only; the OTP is consumed by the reset step.
        await self._check_reset_otp(payload.email.lower(), payload.otp)

    async def reset_password(self, payload: ResetPasswordPayloadSchema) -> None:
        email = payload.email.lower()
        await self._check_reset_otp(email, payload.otp)

        user = await self.repo.get_user_by_email(email)
        if user is None:
            raise OtpExpiredException("OTP has expired, please request a new one")

        await self.repo.set_password(user, hash_password(payload.new_password))
        await self.repo.clear_reset_otp(email)

    # ------------------------------ Change password ------------------------------

    async def change_password(
        self, payload: ChangePasswordPayloadSchema, user: User
    ) -> None:
        if not verify_password(payload.old_password, user.password_hash):
            raise BadRequestException("Old password is incorrect")

        await self.repo.set_password(user, hash_password(payload.new_password))
