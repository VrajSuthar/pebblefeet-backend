import hashlib
import hmac

from app.services.razorpay_client import RazorpayClient

client = RazorpayClient(key_id="rzp_test_x", key_secret="secret", webhook_secret="whsec")


def test_checkout_signature():
    good = hmac.new(b"secret", b"order_1|pay_1", hashlib.sha256).hexdigest()
    assert client.verify_payment_signature("order_1", "pay_1", good)
    assert not client.verify_payment_signature("order_1", "pay_2", good)
    assert not client.verify_payment_signature("order_1", "pay_1", "0" * 64)


def test_webhook_signature_is_over_raw_body():
    body = b'{"event":"payment.captured"}'
    good = hmac.new(b"whsec", body, hashlib.sha256).hexdigest()
    assert client.verify_webhook_signature(body, good)
    # Re-serialised JSON (different bytes) must not pass
    assert not client.verify_webhook_signature(b'{"event": "payment.captured"}', good)


def test_webhook_rejected_without_secret():
    no_secret = RazorpayClient(key_id="k", key_secret="s", webhook_secret="")
    assert not no_secret.verify_webhook_signature(b"{}", "")
