import json
from decimal import Decimal
from functools import lru_cache
from typing import Annotated

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str
    app_description: str
    version: str

    environment: str
    debug: bool = False

    secret_key: str
    jwt_algorithm: str
    access_token_expire_minutes: int
    refresh_token_expire_days: int

    database_url: str
    redis_url: str

    # Comma-separated ("https://a.com,https://b.com") or a JSON list (["*"])
    cors_origins: Annotated[list[str], NoDecode] = []

    # Razorpay: keys from Dashboard -> Account & Settings -> API Keys,
    # webhook secret is the one typed in when creating the webhook.
    razorpay_key_id: str = ""
    razorpay_key_secret: str = ""
    razorpay_webhook_secret: str = ""

    # Checkout rules (prices are GST-inclusive, as printed on the pack)
    shipping_fee: Decimal = Decimal("50")
    free_shipping_threshold: Decimal = Decimal("499")
    cod_enabled: bool = True
    cod_max_order_amount: Decimal = Decimal("5000")
    max_quantity_per_item: int = 10
    # Unpaid Razorpay orders are cancelled after this and their stock released
    pending_order_ttl_minutes: int = 30
    return_window_days: int = 7

    # Used by `python -m app.scripts.seed_admin`
    default_admin_email: str = ""
    default_admin_password: str = ""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value):
        if isinstance(value, str):
            value = value.strip()
            if value.startswith("["):
                return json.loads(value)
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def razorpay_enabled(self) -> bool:
        return bool(self.razorpay_key_id and self.razorpay_key_secret)


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore


settings = get_settings()
