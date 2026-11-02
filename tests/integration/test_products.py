import uuid


async def test_product_crud(client, customer, admin):
    _, headers = customer
    _, admin_headers = admin
    tag = uuid.uuid4().hex[:8]

    assert (await client.get("/products")).status_code == 401
    r = await client.post("/products/categories", json={"name": "X"}, headers=headers)
    assert r.status_code == 403

    category = (await client.post("/products/categories", json={"name": f"Herbal {tag}"},
                                  headers=admin_headers)).json()["data"]
    payload = {
        "category_id": category["id"],
        "name": f"Neem Soap {tag}",
        "skin_types": ["Oily"],
        "variants": [{"sku": f"N-{tag}", "name": "100g", "weight_grams": 100,
                      "price": "120.00", "mrp": "150.00", "stock": 10}],
        "images": [{"image_url": "https://img.test/1.jpg", "is_primary": True}],
    }
    product = (await client.post("/products", json=payload, headers=admin_headers)).json()["data"]
    assert product["slug"] == f"neem-soap-{tag}" and product["skin_types"] == ["oily"]

    second = (await client.post("/products", json={**payload, "variants": [], "images": []},
                                headers=admin_headers)).json()["data"]
    assert second["slug"] == f"neem-soap-{tag}-2"
    r = await client.post("/products", json={**payload, "name": "Other", "images": []}, headers=admin_headers)
    assert r.status_code == 409  # duplicate SKU

    updated = (await client.patch(f"/products/{product['id']}", json={"is_featured": True},
                                  headers=admin_headers)).json()["data"]
    assert updated["is_featured"] is True and updated["slug"] == product["slug"]
    r = await client.patch(f"/products/{product['id']}", json={"name": None}, headers=admin_headers)
    assert r.status_code == 422

    variant_id = product["variants"][0]["id"]
    r = await client.patch(f"/products/variants/{variant_id}", json={"mrp": "100"}, headers=admin_headers)
    assert r.status_code == 400  # MRP below price

    await client.delete(f"/products/{product['id']}", headers=admin_headers)
    assert (await client.get(f"/products/{product['slug']}", headers=headers)).status_code == 404
    assert (await client.get(f"/products/id/{product['id']}", headers=admin_headers)).status_code == 200
