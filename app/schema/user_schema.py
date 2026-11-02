import re
import uuid
from datetime import datetime
from typing import Self

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from app.model.user_model import AddressType, UserRole
from app.schema.auth_schema import normalise_phone
from app.schema.common_schema import PageQuerySchema, PartialUpdateSchema

INDIA = "India"
PIN_CODE_PATTERN = re.compile(r"^[1-9][0-9]{5}$")


def _strip_optional(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    if not value:
        raise ValueError("Cannot be blank")
    return value


def _phone_optional(value: str | None) -> str | None:
    return None if value is None else normalise_phone(value)


# ------------------------------ Profile ------------------------------


class UserProfileSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    first_name: str
    last_name: str
    email: EmailStr
    phone_number: str
    role: UserRole
    is_email_verified: bool
    created_at: datetime


class UserUpdatePayloadSchema(PartialUpdateSchema):
    non_nullable = frozenset({"first_name", "last_name", "phone_number"})

    first_name: str | None = Field(default=None, min_length=1, max_length=50)
    last_name: str | None = Field(default=None, min_length=1, max_length=50)
    phone_number: str | None = None

    _strip_names = field_validator("first_name", "last_name")(_strip_optional)
    _clean_phone = field_validator("phone_number")(_phone_optional)


class DeleteAccountPayloadSchema(BaseModel):
    # Re-entering the password guards against a stolen access token
    password: str = Field(min_length=1, max_length=64)


# ------------------------------ Addresses ------------------------------


class AddressResponseSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    recipient_name: str
    phone_number: str
    address_line1: str
    address_line2: str | None
    landmark: str | None
    city: str
    state: str
    postal_code: str
    country: str
    address_type: AddressType
    is_default: bool


def _check_pin_code(country: str | None, postal_code: str | None) -> None:
    if (country or INDIA) == INDIA and postal_code is not None:
        if not PIN_CODE_PATTERN.match(postal_code):
            raise ValueError("Enter a valid 6-digit PIN code")


class AddressCreatePayloadSchema(BaseModel):
    recipient_name: str = Field(min_length=1, max_length=255)
    phone_number: str
    address_line1: str = Field(min_length=1, max_length=500)
    address_line2: str | None = Field(default=None, max_length=500)
    landmark: str | None = Field(default=None, max_length=255)
    city: str = Field(min_length=1, max_length=100)
    state: str = Field(min_length=1, max_length=100)
    postal_code: str = Field(min_length=3, max_length=20)
    country: str = Field(default=INDIA, min_length=1, max_length=100)
    address_type: AddressType = AddressType.HOME
    is_default: bool = False

    _strip_text = field_validator(
        "recipient_name", "address_line1", "city", "state", "postal_code", "country"
    )(_strip_optional)
    _clean_phone = field_validator("phone_number")(normalise_phone)

    @model_validator(mode="after")
    def check_pin_code(self) -> Self:
        _check_pin_code(self.country, self.postal_code)
        return self


class AddressUpdatePayloadSchema(PartialUpdateSchema):
    non_nullable = frozenset(
        {
            "recipient_name",
            "phone_number",
            "address_line1",
            "city",
            "state",
            "postal_code",
            "country",
            "address_type",
            "is_default",
        }
    )

    recipient_name: str | None = Field(default=None, min_length=1, max_length=255)
    phone_number: str | None = None
    address_line1: str | None = Field(default=None, min_length=1, max_length=500)
    address_line2: str | None = Field(default=None, max_length=500)
    landmark: str | None = Field(default=None, max_length=255)
    city: str | None = Field(default=None, min_length=1, max_length=100)
    state: str | None = Field(default=None, min_length=1, max_length=100)
    postal_code: str | None = Field(default=None, min_length=3, max_length=20)
    country: str | None = Field(default=None, min_length=1, max_length=100)
    address_type: AddressType | None = None
    is_default: bool | None = None

    _strip_text = field_validator(
        "recipient_name", "address_line1", "city", "state", "postal_code", "country"
    )(_strip_optional)
    _clean_phone = field_validator("phone_number")(_phone_optional)


# ------------------------------ Admin ------------------------------


class AdminUserSchema(UserProfileSchema):
    is_active: bool
    last_login_at: datetime | None


class AdminUserQuerySchema(PageQuerySchema):
    # Matches name, email or phone
    search: str | None = Field(default=None, max_length=100)
    role: UserRole | None = None
    is_active: bool | None = None


class AdminUserUpdatePayloadSchema(PartialUpdateSchema):
    non_nullable = frozenset({"is_active", "role"})

    is_active: bool | None = None
    role: UserRole | None = None
