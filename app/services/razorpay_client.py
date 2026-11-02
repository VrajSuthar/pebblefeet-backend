"""Thin async client for the Razorpay REST API (https://razorpay.com/docs/api/).

All amounts are in paise. Signature checks follow Razorpay's docs:
  checkout:  HMAC_SHA256(order_id + "|" + payment_id, key_secret)
  webhook:   HMAC_SHA256(raw request body, webhook_secret)
"""

import hashlib
import hmac
import logging
from typing import Any

import httpx

from app.core.exceptions import PaymentGatewayException, ServiceUnavailableException
from app.core.settings import settings

logger = logging.getLogger(__name__)

BASE_URL = "https://api.razorpay.com/v1"
TIMEOUT_SECONDS = 15.0


def _hmac_sha256(secret: str, message: bytes) -> str:
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


class RazorpayClient:
    def __init__(
        self,
        key_id: str | None = None,
        key_secret: str | None = None,
        webhook_secret: str | None = None,
    ):
        self.key_id = key_id if key_id is not None else settings.razorpay_key_id
        self.key_secret = key_secret if key_secret is not None else settings.razorpay_key_secret
        self.webhook_secret = (
            webhook_secret if webhook_secret is not None else settings.razorpay_webhook_secret
        )

    # ------------------------------ Signatures ------------------------------

    def verify_payment_signature(
        self, razorpay_order_id: str, razorpay_payment_id: str, signature: str
    ) -> bool:
        expected = _hmac_sha256(
            self.key_secret, f"{razorpay_order_id}|{razorpay_payment_id}".encode()
        )
        return hmac.compare_digest(expected, signature)

    def verify_webhook_signature(self, body: bytes, signature: str) -> bool:
        if not self.webhook_secret:
            return False
        return hmac.compare_digest(_hmac_sha256(self.webhook_secret, body), signature)

    # ------------------------------ API calls ------------------------------

    async def _request(
        self, method: str, path: str, json: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        if not (self.key_id and self.key_secret):
            raise ServiceUnavailableException("Online payments are not available right now")

        try:
            async with httpx.AsyncClient(
                base_url=BASE_URL, auth=(self.key_id, self.key_secret), timeout=TIMEOUT_SECONDS
            ) as client:
                response = await client.request(method, path, json=json)
        except httpx.HTTPError as exc:
            logger.error("Razorpay %s %s failed: %s", method, path, type(exc).__name__)
            raise PaymentGatewayException(
                "Could not reach the payment gateway, please try again"
            ) from exc

        if response.status_code >= 400:
            # Razorpay errors look like {"error": {"code": ..., "description": ...}}
            try:
                error = response.json().get("error", {})
            except ValueError:
                error = {}
            logger.error(
                "Razorpay %s %s -> %d %s", method, path, response.status_code, error
            )
            raise PaymentGatewayException(
                error.get("description") or "Payment gateway rejected the request"
            )
        return response.json()

    async def create_order(
        self, amount_paise: int, receipt: str, notes: dict[str, str]
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/orders",
            json={
                "amount": amount_paise,
                "currency": "INR",
                "receipt": receipt,
                "notes": notes,
            },
        )

    async def fetch_order(self, razorpay_order_id: str) -> dict[str, Any]:
        return await self._request("GET", f"/orders/{razorpay_order_id}")

    async def fetch_order_payments(self, razorpay_order_id: str) -> list[dict[str, Any]]:
        data = await self._request("GET", f"/orders/{razorpay_order_id}/payments")
        return data.get("items", [])

    async def fetch_payment(self, razorpay_payment_id: str) -> dict[str, Any]:
        return await self._request("GET", f"/payments/{razorpay_payment_id}")

    async def capture_payment(
        self, razorpay_payment_id: str, amount_paise: int
    ) -> dict[str, Any]:
        # Only needed when auto-capture is off in the Razorpay dashboard
        return await self._request(
            "POST",
            f"/payments/{razorpay_payment_id}/capture",
            json={"amount": amount_paise, "currency": "INR"},
        )

    async def refund_payment(
        self, razorpay_payment_id: str, amount_paise: int, notes: dict[str, str]
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            f"/payments/{razorpay_payment_id}/refund",
            json={"amount": amount_paise, "notes": notes},
        )


def get_razorpay_client() -> RazorpayClient:
    return RazorpayClient()
