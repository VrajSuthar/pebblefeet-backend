import re
import uuid
from typing import Self

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    field_validator,
    model_validator,
)

PASSWORD_MIN_LENGTH = 8
PASSWORD_MAX_LENGTH = 64
PHONE_PATTERN = re.compile(r"^\+?[0-9]{10,15}$")


def normalise_phone(value: str) -> str:
    value = re.sub(r"[\s-]", "", value)
    if not PHONE_PATTERN.match(value):
        raise ValueError("Enter a valid phone number")
    return value


def _validate_password_strength(value: str) -> str:
    if not re.search(r"[A-Z]", value):
        raise ValueError("Password must contain at least one uppercase letter")
    if not re.search(r"[a-z]", value):
        raise ValueError("Password must contain at least one lowercase letter")
    if not re.search(r"[0-9]", value):
        raise ValueError("Password must contain at least one digit")
    return value


class DeviceInfoSchema(BaseModel):
    device_name: str = Field(min_length=1, max_length=100)
    player_id: str = Field(min_length=1, max_length=100)


class LoginPayloadSchema(DeviceInfoSchema):
    email: EmailStr
    password: str = Field(min_length=1, max_length=PASSWORD_MAX_LENGTH)


class SignUpPayloadSchema(DeviceInfoSchema):
    first_name: str = Field(min_length=1, max_length=50)
    last_name: str = Field(min_length=1, max_length=50)
    phone_number: str
    email: EmailStr
    password: str = Field(min_length=PASSWORD_MIN_LENGTH, max_length=PASSWORD_MAX_LENGTH)
    confirm_password: str

    @field_validator("first_name", "last_name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Name cannot be blank")
        return value

    @field_validator("phone_number")
    @classmethod
    def validate_phone(cls, value: str) -> str:
        return normalise_phone(value)

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        return _validate_password_strength(value)

    @model_validator(mode="after")
    def passwords_match(self) -> Self:
        if self.password != self.confirm_password:
            raise ValueError("Passwords do not match")
        return self


class RefreshTokenPayloadSchema(BaseModel):
    refresh_token: str


class LogoutPayloadSchema(BaseModel):
    refresh_token: str
    player_id: str | None = None


class ForgotPasswordRequestSchema(BaseModel):
    """Step 1: ask for an OTP to be sent to the email."""

    email: EmailStr


class ForgotPasswordPayloadSchema(BaseModel):
    """Step 2: verify the OTP."""

    email: EmailStr
    otp: str = Field(pattern=r"^[0-9]{6}$")


class ResetPasswordPayloadSchema(BaseModel):
    """Step 3: set the new password after the OTP was verified."""

    email: EmailStr
    otp: str = Field(pattern=r"^[0-9]{6}$")
    new_password: str = Field(min_length=PASSWORD_MIN_LENGTH, max_length=PASSWORD_MAX_LENGTH)
    confirm_password: str

    @field_validator("new_password")
    @classmethod
    def validate_new_password(cls, value: str) -> str:
        return _validate_password_strength(value)

    @model_validator(mode="after")
    def passwords_match(self) -> Self:
        if self.new_password != self.confirm_password:
            raise ValueError("Passwords do not match")
        return self


class ChangePasswordPayloadSchema(BaseModel):
    old_password: str = Field(min_length=1, max_length=PASSWORD_MAX_LENGTH)
    new_password: str = Field(min_length=PASSWORD_MIN_LENGTH, max_length=PASSWORD_MAX_LENGTH)

    @field_validator("new_password")
    @classmethod
    def validate_new_password(cls, value: str) -> str:
        return _validate_password_strength(value)

    @model_validator(mode="after")
    def password_changed(self) -> Self:
        if self.old_password == self.new_password:
            raise ValueError("New password must be different from the old password")
        return self


class TokenResponseSchema(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int



class UserResponseSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    first_name: str
    last_name: str
    email: EmailStr
    phone_number: str


class AuthResponseSchema(TokenResponseSchema):
    user: UserResponseSchema
