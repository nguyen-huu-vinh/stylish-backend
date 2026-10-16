from conftest import login


def order_body(product, qty=1, **extra):
    body = {
        "full_name": "A", "phone": "0900000000", "address": "1 Nguyễn Huệ, Q1",
        "payment_method": "cod",
        "items": [{"product_id": product["id"], "size": "38", "quantity": qty}],
    }
    body.update(extra)
    return body


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_email_is_case_insensitive(client):
    assert client.post("/register", json={"email": "Case@X.com", "password": "secret123"}).status_code == 201
    assert client.post("/register", json={"email": "case@x.COM", "password": "secret123"}).status_code == 400
    login(client, "CASE@x.com", "secret123")


def test_password_policy(client):
    for pw in ("short1", "onlyletters", "12345678"):
        r = client.post("/register", json={"email": f"{pw}@x.com", "password": pw})
        assert r.status_code == 400, pw


def test_login_rate_limit(client):
    for _ in range(10):
        client.post("/login", data={"username": "no@x.com", "password": "bad"})
    assert client.post("/login", data={"username": "no@x.com", "password": "bad"}).status_code == 429


def test_forgot_password_does_not_reveal_accounts(client, monkeypatch):
    import routers.auth as auth

    monkeypatch.setattr(auth, "is_mailtrap_configured", lambda: True)
    r = client.post("/forgot-password", json={"email": "ghost@x.com"})
    assert r.status_code == 200


def test_order_reduces_stock_and_cancel_restores(client, user, product):
    r = client.post("/orders", json=order_body(product, 2), headers=user)
    assert r.status_code == 201, r.text
    oid = r.json()["id"]
    assert client.get(f"/products/{product['id']}").json()["stock"] == 1
    assert client.post(f"/orders/{oid}/cancel", json={}, headers=user).status_code == 200
    assert client.get(f"/products/{product['id']}").json()["stock"] == 3


def test_cannot_oversell(client, user, product):
    assert client.post("/orders", json=order_body(product, 4), headers=user).status_code == 400


def test_status_transitions(client, admin, user, product):
    oid = client.post("/orders", json=order_body(product), headers=user).json()["id"]
    url = f"/admin/orders/{oid}/status"
    assert client.put(url, json={"status": "completed"}, headers=admin).status_code == 400
    for status in ("confirmed", "shipping", "completed"):
        assert client.put(url, json={"status": status}, headers=admin).status_code == 200
    assert client.put(url, json={"status": "pending"}, headers=admin).status_code == 400
    assert client.put(url, json={"status": "cancelled"}, headers=admin).status_code == 400


def test_soft_delete_product_keeps_old_orders(client, admin, user, product):
    oid = client.post("/orders", json=order_body(product), headers=user).json()["id"]
    assert client.delete(f"/products/{product['id']}", headers=admin).status_code == 200
    assert client.get(f"/products/{product['id']}").status_code == 404
    assert product["id"] not in [p["id"] for p in client.get("/products").json()]
    assert client.get(f"/orders/{oid}", headers=user).status_code == 200
    assert client.post("/orders", json=order_body(product), headers=user).status_code == 400


def test_products_pagination(client, admin, product):
    assert len(client.get("/products?limit=1").json()) == 1
    assert client.get("/products?limit=0").status_code == 422


def test_shipper_token_via_header(client, admin, user, product):
    oid = client.post("/orders", json=order_body(product), headers=user).json()["id"]
    url = f"/admin/orders/{oid}/status"
    client.put(url, json={"status": "shipping"}, headers=admin)
    token = client.get("/admin/orders", headers=admin).json()
    token = next(o for o in token if o["id"] == oid).get("tracking_token")
    if token:
        ok = client.get(f"/shipper/orders/{oid}", headers={"X-Shipper-Token": token})
        assert ok.status_code == 200
    bad = client.get(f"/shipper/orders/{oid}", headers={"X-Shipper-Token": "x" * 20})
    assert bad.status_code == 404
