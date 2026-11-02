

async def test_reviews_ratings_and_moderation(client, db, customer, make_user, admin, catalog, address):
    user, headers = customer
    _, other_headers = await make_user()
    _, admin_headers = admin
    product_id = str(catalog["product"].id)

    r = await client.post("/reviews", json={"product_id": product_id, "rating": 5, "title": " Lovely "},
                          headers=headers)
    assert r.status_code == 201
    review = r.json()["data"]
    assert review["title"] == "Lovely" and review["reviewer_name"] == "Test C."
    assert review["is_verified_purchase"] is False

    r = await client.post("/reviews", json={"product_id": product_id, "rating": 4}, headers=headers)
    assert r.status_code == 409
    await client.post("/reviews", json={"product_id": product_id, "rating": 2}, headers=other_headers)

    reviews = (await client.get(f"/reviews/product/{product_id}", headers=headers)).json()["data"]
    assert reviews["summary"] == {"average": "3.5", "count": 2,
                                  "distribution": {"5": 1, "4": 0, "3": 0, "2": 1, "1": 0}}
    listing = (await client.get("/products", params={"search": catalog["product"].name},
                                headers=headers)).json()["data"]
    assert listing["items"][0]["rating_average"] == "3.5" and listing["items"][0]["review_count"] == 2

    # Others can't edit it; after a delivered order the author earns the badge
    r = await client.patch(f"/reviews/{review['id']}", json={"rating": 1}, headers=other_headers)
    assert r.status_code == 403
    await client.post("/cart/items", json={"variant_id": str(catalog["bar"].id)}, headers=headers)
    order_id = (await client.post("/orders", json={"address_id": str(address.id), "payment_method": "cod"},
                                  headers=headers)).json()["data"]["order"]["id"]
    for status, extra in [("processing", {}), ("shipped", {"courier_name": "DTDC", "tracking_number": "1"}),
                          ("delivered", {})]:
        await client.patch(f"/admin/orders/{order_id}/status", json={"status": status, **extra},
                           headers=admin_headers)
    updated = (await client.patch(f"/reviews/{review['id']}", json={"comment": "Still lovely"},
                                  headers=headers)).json()["data"]
    assert updated["is_verified_purchase"] is True and updated["rating"] == 5

    # Admin hides the 2-star review: it leaves the listing and the average
    hidden = (await client.get("/admin/reviews", params={"rating": 2, "product_id": product_id},
                               headers=admin_headers)).json()["data"]["items"][0]
    await client.patch(f"/admin/reviews/{hidden['id']}", json={"is_approved": False}, headers=admin_headers)
    summary = (await client.get(f"/reviews/product/{product_id}", headers=headers)).json()["data"]["summary"]
    assert summary["average"] == "5.0" and summary["count"] == 1


async def test_admin_blocks_user_and_cannot_demote_self(client, customer, admin):
    user, headers = customer
    admin_user, admin_headers = admin

    found = (await client.get("/admin/users", params={"search": user.email}, headers=admin_headers)).json()["data"]
    assert found["total"] == 1

    r = await client.patch(f"/admin/users/{user.id}", json={"is_active": False}, headers=admin_headers)
    assert r.status_code == 200 and r.json()["data"]["is_active"] is False
    assert (await client.get("/cart", headers=headers)).status_code == 401  # blocked immediately

    r = await client.patch(f"/admin/users/{admin_user.id}", json={"role": "customer"}, headers=admin_headers)
    assert r.status_code == 400


async def test_admin_coupon_crud(client, admin):
    _, admin_headers = admin
    r = await client.post("/admin/coupons", headers=admin_headers, json={
        "code": "welcome-10", "discount_type": "percentage", "discount_value": "110"})
    assert r.status_code == 422  # a percentage above 100 is refused

    body = {"code": "welcome10", "discount_type": "percentage", "discount_value": "10",
            "max_discount_amount": "100"}
    created = (await client.post("/admin/coupons", json=body, headers=admin_headers)).json()["data"]
    assert created["code"] == "WELCOME10"
    assert (await client.post("/admin/coupons", json=body, headers=admin_headers)).status_code == 409

    r = await client.patch(f"/admin/coupons/{created['id']}", json={"discount_value": "150"},
                           headers=admin_headers)
    assert r.status_code == 400
    r = await client.delete(f"/admin/coupons/{created['id']}", headers=admin_headers)
    assert r.status_code == 200
    got = (await client.get(f"/admin/coupons/{created['id']}", headers=admin_headers)).json()["data"]
    assert got["is_active"] is False


async def test_health(client):
    r = await client.get("/health")
    assert r.status_code == 200 and r.json() == {"status": "ok", "database": "ok", "redis": "ok"}


async def test_unknown_route_uses_error_envelope(client):
    r = await client.get("/does-not-exist")
    assert r.status_code == 404 and r.json()["status"] == "error"


