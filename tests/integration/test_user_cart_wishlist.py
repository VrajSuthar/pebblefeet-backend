import uuid

from tests.conftest import PASSWORD


async def test_profile_update_and_phone_conflict(client, customer, make_user):
    user, headers = customer
    other, _ = await make_user()

    r = await client.patch("/users/me", json={"first_name": " Priya "}, headers=headers)
    assert r.status_code == 200 and r.json()["data"]["first_name"] == "Priya"

    r = await client.patch("/users/me", json={"phone_number": other.phone_number}, headers=headers)
    assert r.status_code == 409

    # Cached user must reflect the change on the next request
    r = await client.get("/users/me", headers=headers)
    assert r.json()["data"]["first_name"] == "Priya"


async def test_address_crud_keeps_exactly_one_default(client, customer):
    _, headers = customer
    body = {
        "recipient_name": "Priya", "phone_number": "98765 43210", "address_line1": "1 Ring Rd",
        "city": "Surat", "state": "Gujarat", "postal_code": "395001",
    }
    first = (await client.post("/users/me/addresses", json=body, headers=headers)).json()["data"]
    assert first["is_default"] is True  # first address becomes default
    second = (
        await client.post("/users/me/addresses", json={**body, "is_default": True}, headers=headers)
    ).json()["data"]

    addresses = (await client.get("/users/me/addresses", headers=headers)).json()["data"]
    assert [a["id"] for a in addresses if a["is_default"]] == [second["id"]]

    r = await client.post("/users/me/addresses", json={**body, "postal_code": "12"}, headers=headers)
    assert r.status_code == 422
    assert r.json()["errors"][0]["field"] == "postal_code"  # unified error envelope

    await client.delete(f"/users/me/addresses/{second['id']}", headers=headers)
    addresses = (await client.get("/users/me/addresses", headers=headers)).json()["data"]
    assert len(addresses) == 1 and addresses[0]["is_default"] is True


async def test_cannot_touch_someone_elses_address(client, customer, make_user, address):
    _, intruder_headers = await make_user()
    r = await client.get(f"/users/me/addresses/{address.id}", headers=intruder_headers)
    assert r.status_code == 404


async def test_delete_account_needs_password_and_blocks_login(client, customer):
    _, headers = customer
    r = await client.post("/users/me/delete", json={"password": "wrong"}, headers=headers)
    assert r.status_code == 400
    r = await client.post("/users/me/delete", json={"password": PASSWORD}, headers=headers)
    assert r.status_code == 200
    assert (await client.get("/users/me", headers=headers)).status_code == 401


async def test_cart_add_merge_limits_and_totals(client, customer, catalog):
    _, headers = customer
    bar, pack = catalog["bar"], catalog["pack"]

    await client.post("/cart/items", json={"variant_id": str(bar.id), "quantity": 2}, headers=headers)
    cart = (
        await client.post("/cart/items", json={"variant_id": str(bar.id)}, headers=headers)
    ).json()["data"]
    assert cart["items"][0]["quantity"] == 3  # merged, not duplicated
    assert cart["subtotal"] == "360.00" and cart["shipping_fee"] == "50.00"
    assert cart["amount_for_free_shipping"] == "139.00"

    r = await client.post("/cart/items", json={"variant_id": str(pack.id), "quantity": 3}, headers=headers)
    assert r.status_code == 400 and "Only 2 left" in r.json()["message"]

    item_id = cart["items"][0]["id"]
    cart = (
        await client.patch(f"/cart/items/{item_id}", json={"quantity": 5}, headers=headers)
    ).json()["data"]
    assert cart["total"] == "600.00"  # free shipping from ₹499


async def test_cart_flags_items_that_became_unavailable(client, db, customer, catalog):
    _, headers = customer
    bar = catalog["bar"]
    await client.post("/cart/items", json={"variant_id": str(bar.id), "quantity": 4}, headers=headers)
    bar.stock = 1
    await db.commit()

    cart = (await client.get("/cart", headers=headers)).json()["data"]
    assert cart["has_issues"] is True
    assert cart["items"][0]["issue"] == "Only 1 left in stock"
    assert cart["subtotal"] == "0.00"


async def test_wishlist_is_idempotent(client, customer, catalog):
    _, headers = customer
    product_id = str(catalog["product"].id)
    await client.post("/wishlist", json={"product_id": product_id}, headers=headers)
    items = (await client.post("/wishlist", json={"product_id": product_id}, headers=headers)).json()["data"]
    assert len(items) == 1 and items[0]["product"]["min_price"] == "120.00"

    items = (await client.delete(f"/wishlist/{product_id}", headers=headers)).json()["data"]
    assert items == []
    r = await client.post("/wishlist", json={"product_id": str(uuid.uuid4())}, headers=headers)
    assert r.status_code == 404
