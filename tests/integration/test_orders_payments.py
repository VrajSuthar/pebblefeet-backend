from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.settings import settings
from app.model.coupon_model import Coupon, DiscountType
from app.model.order_model import Order
from app.services.order import OrderService


async def fill_cart(client, headers, variant, quantity):
    r = await client.post(
        "/cart/items", json={"variant_id": str(variant.id), "quantity": quantity}, headers=headers
    )
    assert r.status_code == 200, r.json()


async def place(client, headers, address, method="razorpay", coupon=None):
    body = {"address_id": str(address.id), "payment_method": method}
    if coupon:
        body["coupon_code"] = coupon
    return await client.post("/orders", json=body, headers=headers)


@pytest.fixture
async def coupon(db):
    c = Coupon(
        code=f"SOAP{datetime.now().microsecond}",
        discount_type=DiscountType.PERCENTAGE,
        discount_value=Decimal("10"),
        min_order_amount=Decimal("300"),
        per_user_limit=1,
        usage_limit=5,
        valid_from=datetime.now(timezone.utc) - timedelta(days=1),
    )
    db.add(c)
    await db.commit()
    return c


# ------------------------------ Checkout ------------------------------


async def test_preview_with_coupon(client, customer, catalog, coupon):
    _, headers = customer
    await fill_cart(client, headers, catalog["bar"], 2)  # ₹240, under the ₹300 minimum
    r = await client.post("/orders/preview", json={"coupon_code": coupon.code.lower()}, headers=headers)
    assert r.status_code == 400 and r.json()["errors"][0]["code"] == "COUPON_MIN_ORDER"

    await fill_cart(client, headers, catalog["bar"], 3)  # ₹600
    preview = (
        await client.post("/orders/preview", json={"coupon_code": coupon.code}, headers=headers)
    ).json()["data"]
    assert preview["discount_amount"] == "60.00"
    assert preview["shipping_fee"] == "0.00"
    assert preview["total_amount"] == "540.00"
    assert preview["tax_amount"] == "82.37"  # 18% GST contained in ₹540


async def test_cod_order_reserves_stock_and_cancel_gives_it_back(
    client, db, customer, address, catalog, coupon
):
    _, headers = customer
    bar = catalog["bar"]
    await fill_cart(client, headers, bar, 3)

    r = await place(client, headers, address, method="cod", coupon=coupon.code)
    assert r.status_code == 201, r.json()
    data = r.json()["data"]
    order = data["order"]
    assert data["payment"] is None
    assert order["status"] == "confirmed" and order["payment_method"] == "cod"
    # 3 x 120 = 360, minus 10% = 324, plus 50 shipping (under ₹499) = 374
    assert (order["discount_amount"], order["shipping_fee"], order["total_amount"]) == (
        "36.00", "50.00", "374.00"
    )
    assert order["shipping_address"]["city"] == "Ahmedabad"
    assert order["order_number"].startswith("PF-")

    await db.refresh(bar)
    await db.refresh(coupon)
    assert bar.stock == 7 and coupon.used_count == 1
    assert (await client.get("/cart", headers=headers)).json()["data"]["items"] == []

    # Same coupon twice for the same user is refused
    await fill_cart(client, headers, bar, 3)
    r = await place(client, headers, address, method="cod", coupon=coupon.code)
    assert r.json()["errors"][0]["code"] == "COUPON_ALREADY_USED"

    r = await client.post(f"/orders/{order['id']}/cancel", json={"reason": "Changed mind"}, headers=headers)
    assert r.status_code == 200 and r.json()["data"]["status"] == "cancelled"
    await db.refresh(bar)
    await db.refresh(coupon)
    assert bar.stock == 10 and coupon.used_count == 0


async def test_cannot_buy_more_than_stock(client, db, customer, address, catalog):
    _, headers = customer
    pack = catalog["pack"]
    await fill_cart(client, headers, pack, 2)
    pack.stock = 1  # someone else bought one meanwhile
    await db.commit()

    r = await place(client, headers, address, method="cod")
    assert r.status_code == 400 and "Only 1 left" in r.json()["message"]
    await db.refresh(pack)
    assert pack.stock == 1  # nothing reserved


async def test_empty_cart_and_foreign_address(client, customer, make_user, address):
    _, headers = customer
    r = await place(client, headers, address)
    assert r.json()["errors"][0]["code"] == "CART_EMPTY"

    _, other_headers = await make_user()
    assert (await place(client, other_headers, address)).status_code == 404


# ------------------------------ Razorpay ------------------------------


async def test_razorpay_happy_path_and_idempotent_verify(client, customer, address, catalog, razorpay):
    _, headers = customer
    await fill_cart(client, headers, catalog["bar"], 5)  # ₹600, free shipping

    data = (await place(client, headers, address)).json()["data"]
    checkout = data["payment"]
    assert data["order"]["status"] == "pending"
    assert checkout["amount"] == 60000 and checkout["key_id"] == "rzp_test_fake"
    assert checkout["prefill"]["email"].endswith("@example.com")

    payment_id, signature = razorpay.customer_pays(checkout["razorpay_order_id"])
    bad = {"razorpay_order_id": checkout["razorpay_order_id"], "razorpay_payment_id": payment_id,
           "razorpay_signature": "0" * 64}
    r = await client.post("/payments/verify", json=bad, headers=headers)
    assert r.json()["errors"][0]["code"] == "PAYMENT_SIGNATURE_INVALID"

    good = {**bad, "razorpay_signature": signature}
    order = (await client.post("/payments/verify", json=good, headers=headers)).json()["data"]
    assert order["status"] == "confirmed" and order["payment_status"] == "paid"
    assert order["payments"][0]["method"] == "upi"

    # The webhook for the same payment arriving afterwards changes nothing
    body, webhook_headers = razorpay.webhook("payment.captured", "payment", razorpay.payments[payment_id])
    assert (await client.post("/payments/webhook/razorpay", content=body, headers=webhook_headers)).status_code == 200
    again = (await client.post("/payments/verify", json=good, headers=headers)).json()["data"]
    assert [h["status"] for h in again["status_history"]] == ["pending", "confirmed"]


async def test_webhook_alone_confirms_order(client, customer, address, catalog, razorpay):
    """Customer closed the app before verify; Razorpay's webhook still confirms."""
    _, headers = customer
    await fill_cart(client, headers, catalog["bar"], 1)
    data = (await place(client, headers, address)).json()["data"]
    payment_id, _ = razorpay.customer_pays(data["payment"]["razorpay_order_id"])

    body, webhook_headers = razorpay.webhook("payment.captured", "payment", razorpay.payments[payment_id])
    r = await client.post("/payments/webhook/razorpay", content=body,
                          headers={**webhook_headers, "X-Razorpay-Signature": "forged"})
    assert r.status_code == 400

    r = await client.post("/payments/webhook/razorpay", content=body, headers=webhook_headers)
    assert r.status_code == 200
    order = (await client.get(f"/orders/{data['order']['id']}", headers=headers)).json()["data"]
    assert order["payment_status"] == "paid" and order["status"] == "confirmed"


async def test_failed_payment_then_retry(client, customer, address, catalog, razorpay):
    _, headers = customer
    await fill_cart(client, headers, catalog["bar"], 1)
    data = (await place(client, headers, address)).json()["data"]
    rzp_order_id = data["payment"]["razorpay_order_id"]

    failed = {"id": "pay_failed1", "order_id": rzp_order_id, "status": "failed", "method": "card",
              "error_description": "Card declined"}
    body, webhook_headers = razorpay.webhook("payment.failed", "payment", failed)
    await client.post("/payments/webhook/razorpay", content=body, headers=webhook_headers)

    order = (await client.get(f"/orders/{data['order']['id']}", headers=headers)).json()["data"]
    assert order["payment_status"] == "failed" and order["can_pay"] is True

    retry = (await client.post(f"/orders/{order['id']}/pay", headers=headers)).json()["data"]
    assert retry["razorpay_order_id"] != rzp_order_id  # fresh Razorpay order after a failure


async def test_gateway_down_keeps_order_for_retry(client, customer, address, catalog, razorpay):
    _, headers = customer
    await fill_cart(client, headers, catalog["bar"], 1)
    razorpay.down = True
    data = (await place(client, headers, address)).json()["data"]
    assert data["payment"] is None and "payment gateway" in data["payment_error"]

    razorpay.down = False
    r = await client.post(f"/orders/{data['order']['id']}/pay", headers=headers)
    assert r.status_code == 200 and r.json()["data"]["amount"] == 17000  # 120 + 50 shipping


async def test_cancel_paid_order_refunds(client, customer, address, catalog, razorpay):
    _, headers = customer
    await fill_cart(client, headers, catalog["bar"], 1)
    data = (await place(client, headers, address)).json()["data"]
    payment_id, signature = razorpay.customer_pays(data["payment"]["razorpay_order_id"])
    await client.post("/payments/verify", headers=headers, json={
        "razorpay_order_id": data["payment"]["razorpay_order_id"],
        "razorpay_payment_id": payment_id, "razorpay_signature": signature})

    order = (await client.post(f"/orders/{data['order']['id']}/cancel", json={}, headers=headers)).json()["data"]
    assert order["status"] == "cancelled" and order["payment_status"] == "refunded"
    assert razorpay.refunds[0]["payment_id"] == payment_id and razorpay.refunds[0]["amount"] == 17000


# ------------------------------ Unpaid-order sweeper ------------------------------


async def _age(db, order_id, minutes):
    order = (await db.execute(select(Order).where(Order.id == order_id))).scalars().one()
    order.created_at = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    await db.commit()


async def test_sweeper_cancels_unpaid_and_confirms_missed_payments(
    client, db, customer, address, catalog, razorpay
):
    _, headers = customer
    bar = catalog["bar"]
    await fill_cart(client, headers, bar, 2)
    unpaid = (await place(client, headers, address)).json()["data"]
    await fill_cart(client, headers, bar, 3)
    paid = (await place(client, headers, address)).json()["data"]
    # Paid at Razorpay but neither verify nor the webhook reached us
    razorpay.customer_pays(paid["payment"]["razorpay_order_id"])

    ttl = settings.pending_order_ttl_minutes
    await _age(db, unpaid["order"]["id"], ttl + 1)
    await _age(db, paid["order"]["id"], ttl + 1)

    await OrderService(db, razorpay=razorpay).expire_stale_orders()

    unpaid_now = (await client.get(f"/orders/{unpaid['order']['id']}", headers=headers)).json()["data"]
    paid_now = (await client.get(f"/orders/{paid['order']['id']}", headers=headers)).json()["data"]
    assert unpaid_now["status"] == "cancelled"
    assert paid_now["status"] == "confirmed" and paid_now["payment_status"] == "paid"
    await db.refresh(bar)
    assert bar.stock == 7  # 2 released, 3 still sold


async def test_payment_after_expiry_is_refunded(client, db, customer, address, catalog, razorpay):
    _, headers = customer
    await fill_cart(client, headers, catalog["bar"], 1)
    data = (await place(client, headers, address)).json()["data"]
    await _age(db, data["order"]["id"], settings.pending_order_ttl_minutes + 1)
    await OrderService(db, razorpay=razorpay).expire_stale_orders()

    # Customer completes the payment in a tab left open
    payment_id, _ = razorpay.customer_pays(data["payment"]["razorpay_order_id"])
    body, webhook_headers = razorpay.webhook("payment.captured", "payment", razorpay.payments[payment_id])
    await client.post("/payments/webhook/razorpay", content=body, headers=webhook_headers)

    order = (await client.get(f"/orders/{data['order']['id']}", headers=headers)).json()["data"]
    assert order["status"] == "cancelled" and order["payment_status"] == "refunded"
    assert len(razorpay.refunds) == 1


# ------------------------------ Admin workflow ------------------------------


async def test_admin_fulfilment_and_return(client, customer, admin, address, catalog, razorpay, db):
    _, headers = customer
    _, admin_headers = admin
    await fill_cart(client, headers, catalog["bar"], 5)
    data = (await place(client, headers, address)).json()["data"]
    order_id = data["order"]["id"]
    payment_id, signature = razorpay.customer_pays(data["payment"]["razorpay_order_id"])
    await client.post("/payments/verify", headers=headers, json={
        "razorpay_order_id": data["payment"]["razorpay_order_id"],
        "razorpay_payment_id": payment_id, "razorpay_signature": signature})

    async def move(status, **extra):
        return await client.patch(f"/admin/orders/{order_id}/status",
                                  json={"status": status, **extra}, headers=admin_headers)

    assert (await move("delivered")).json()["errors"][0]["code"] == "INVALID_STATUS_TRANSITION"
    assert (await move("processing")).status_code == 200
    assert (await move("shipped")).status_code == 400  # tracking required
    shipped = (await move("shipped", courier_name="Delhivery", tracking_number="DLV123")).json()["data"]
    assert shipped["shipped_at"] and shipped["customer"]["email"].endswith("@example.com")
    assert (await move("delivered")).json()["data"]["can_return"] is True

    # Customers can't use admin endpoints
    assert (await client.get("/admin/orders", headers=headers)).status_code == 403

    r = await client.post(f"/orders/{order_id}/return", json={"reason": "Box was damaged"}, headers=headers)
    assert r.json()["data"]["status"] == "return_requested"
    returned = (await move("returned", note="Received back")).json()["data"]
    assert returned["payment_status"] == "refunded"
    await db.refresh(catalog["bar"])
    assert catalog["bar"].stock == 10

    listing = (await client.get("/admin/orders", params={"search": data["order"]["order_number"]},
                                headers=admin_headers)).json()["data"]
    assert listing["total"] == 1 and listing["items"][0]["status"] == "returned"

    dashboard = (await client.get("/admin/dashboard", headers=admin_headers)).json()["data"]
    assert dashboard["orders_by_status"]["returned"] >= 1


async def test_cod_marked_paid_on_delivery(client, customer, admin, address, catalog):
    _, headers = customer
    _, admin_headers = admin
    await fill_cart(client, headers, catalog["bar"], 1)
    order_id = (await place(client, headers, address, method="cod")).json()["data"]["order"]["id"]
    for status, extra in [("processing", {}), ("shipped", {"courier_name": "DTDC", "tracking_number": "X1"}),
                          ("delivered", {})]:
        r = await client.patch(f"/admin/orders/{order_id}/status",
                               json={"status": status, **extra}, headers=admin_headers)
    assert r.json()["data"]["payment_status"] == "paid"
