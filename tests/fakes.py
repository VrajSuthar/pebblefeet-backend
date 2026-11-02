import hashlib
import hmac
import json
import uuid
from typing import Any

from app.core.exceptions import PaymentGatewayException
from app.services.razorpay_client import RazorpayClient

KEY_SECRET = "test_key_secret"
WEBHOOK_SECRET = "test_webhook_secret"


class FakeRazorpay(RazorpayClient):
    """In-memory Razorpay. Signatures are computed exactly like the real one,
    so the production verification code is what gets tested."""

    def __init__(self):
        super().__init__(
            key_id="rzp_test_fake", key_secret=KEY_SECRET, webhook_secret=WEBHOOK_SECRET
        )
        self.orders: dict[str, dict[str, Any]] = {}
        self.payments: dict[str, dict[str, Any]] = {}
        self.refunds: list[dict[str, Any]] = []
        self.down = False

    def _check_up(self) -> None:
        if self.down:
            raise PaymentGatewayException("Could not reach the payment gateway, please try again")

    # ---- API ----

    async def create_order(self, amount_paise, receipt, notes):
        self._check_up()
        order = {
            "id": f"order_{uuid.uuid4().hex[:14]}",
            "amount": amount_paise,
            "currency": "INR",
            "receipt": receipt,
            "notes": notes,
            "status": "created",
        }
        self.orders[order["id"]] = order
        return order

    async def fetch_order(self, razorpay_order_id):
        self._check_up()
        return self.orders[razorpay_order_id]

    async def fetch_order_payments(self, razorpay_order_id):
        self._check_up()
        return [p for p in self.payments.values() if p["order_id"] == razorpay_order_id]

    async def fetch_payment(self, razorpay_payment_id):
        self._check_up()
        return dict(self.payments[razorpay_payment_id])

    async def capture_payment(self, razorpay_payment_id, amount_paise):
        self.payments[razorpay_payment_id]["status"] = "captured"
        return dict(self.payments[razorpay_payment_id])

    async def refund_payment(self, razorpay_payment_id, amount_paise, notes):
        self._check_up()
        refund = {
            "id": f"rfnd_{uuid.uuid4().hex[:14]}",
            "payment_id": razorpay_payment_id,
            "amount": amount_paise,
        }
        self.refunds.append(refund)
        return refund

    # ---- Test helpers ----

    def customer_pays(
        self, razorpay_order_id: str, status: str = "captured", method: str = "upi"
    ) -> tuple[str, str]:
        """Simulate the customer finishing Checkout. Returns (payment_id, signature)."""
        order = self.orders[razorpay_order_id]
        payment_id = f"pay_{uuid.uuid4().hex[:14]}"
        self.payments[payment_id] = {
            "id": payment_id,
            "order_id": razorpay_order_id,
            "amount": order["amount"],
            "currency": "INR",
            "status": status,
            "method": method,
        }
        if status == "captured":
            order["status"] = "paid"
        signature = hmac.new(
            KEY_SECRET.encode(), f"{razorpay_order_id}|{payment_id}".encode(), hashlib.sha256
        ).hexdigest()
        return payment_id, signature

    @staticmethod
    def webhook(event: str, entity_name: str, entity: dict[str, Any]) -> tuple[bytes, dict[str, str]]:
        body = json.dumps(
            {"event": event, "payload": {entity_name: {"entity": entity}}}
        ).encode()
        signature = hmac.new(WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()
        return body, {
            "X-Razorpay-Signature": signature,
            "X-Razorpay-Event-Id": f"evt_{uuid.uuid4().hex}",
            "Content-Type": "application/json",
        }
