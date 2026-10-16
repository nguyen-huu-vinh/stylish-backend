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


def test_users_list_does_not_leak_password_hash(client, admin):
    r = client.get("/users", headers=admin)
    assert r.status_code == 200
    assert "hashed_password" not in r.text


def test_paid_flag_and_cod_auto_paid(client, admin, user, product):
    oid = client.post("/orders", json=order_body(product), headers=user).json()["id"]
    assert client.get(f"/orders/{oid}", headers=user).json()["paid"] is False
    for status in ("confirmed", "shipping", "completed"):
        client.put(f"/admin/orders/{oid}/status", json={"status": status}, headers=admin)
    done = client.get(f"/orders/{oid}", headers=user).json()
    assert done["paid"] is True and done["paid_at"]


def test_admin_marks_order_paid(client, admin, user, product):
    oid = client.post("/orders", json=order_body(product), headers=user).json()["id"]
    r = client.put(f"/admin/orders/{oid}/paid", headers=admin)
    assert r.status_code == 200 and r.json()["paid"] is True
    assert client.put(f"/admin/orders/{oid}/paid", headers=user).status_code in (401, 403)


def test_admin_stats(client, admin):
    r = client.get("/admin/stats", headers=admin)
    assert r.status_code == 200
    assert {"orders_by_status", "revenue", "daily", "top_products"} <= r.json().keys()


def test_order_is_geocoded_in_background(client, user, product):
    oid = client.post("/orders", json=order_body(product), headers=user).json()["id"]
    track = client.get(f"/orders/{oid}/tracking", headers=user).json()
    assert track["destination"]["lat"] == 10.0


def test_logout_all_revokes_tokens(client, user):
    assert client.get("/me", headers=user).status_code == 200
    assert client.post("/logout-all", headers=user).status_code == 200
    assert client.get("/me", headers=user).status_code == 401


def _completed_order(client, admin, user, product):
    oid = client.post("/orders", json=order_body(product), headers=user).json()["id"]
    for status in ("confirmed", "shipping", "completed"):
        client.put(f"/admin/orders/{oid}/status", json={"status": status}, headers=admin)
    return oid


def test_return_and_refund_flow(client, admin, user, product):
    oid = _completed_order(client, admin, user, product)
    stock_after_sale = client.get(f"/products/{product['id']}").json()["stock"]

    assert client.post(f"/orders/{oid}/return", json={"reason": "ab"}, headers=user).status_code == 422
    r = client.post(f"/orders/{oid}/return", json={"reason": "Sản phẩm bị lỗi"}, headers=user)
    assert r.status_code == 201
    rid = r.json()["return_request"]["id"]
    assert client.post(f"/orders/{oid}/return", json={"reason": "Lần hai nữa"}, headers=user).status_code == 400

    # Chưa duyệt thì chưa hoàn tiền được; không nhảy cóc trạng thái
    assert client.post(f"/admin/orders/{oid}/refund", json={}, headers=admin).status_code == 400
    assert client.put(f"/admin/returns/{rid}", json={"status": "received"}, headers=admin).status_code == 400
    assert client.put(f"/admin/returns/{rid}", json={"status": "approved"}, headers=admin).status_code == 200
    done = client.put(f"/admin/returns/{rid}", json={"status": "received"}, headers=admin)
    assert done.status_code == 200
    assert client.get(f"/products/{product['id']}").json()["stock"] == stock_after_sale + 1

    assert client.post(f"/admin/orders/{oid}/refund", json={"amount": 10**9}, headers=admin).status_code == 400
    ok = client.post(f"/admin/orders/{oid}/refund", json={}, headers=admin)
    assert ok.status_code == 200
    body = ok.json()
    assert body["refund_amount"] == body["total"] and body["return_request"]["status"] == "refunded"
    assert client.post(f"/admin/orders/{oid}/refund", json={}, headers=admin).status_code == 400
    assert len(client.get("/admin/returns", headers=admin).json()) >= 1


def test_cannot_return_unfinished_or_foreign_order(client, admin, user, product):
    oid = client.post("/orders", json=order_body(product), headers=user).json()["id"]
    assert client.post(f"/orders/{oid}/return", json={"reason": "Không thích"}, headers=user).status_code == 400
    done = _completed_order(client, admin, user, product)
    other = client.post("/register", json={"email": "other1@x.com", "password": "secret123"})
    stranger = login(client, "other1@x.com", "secret123")
    assert client.post(f"/orders/{done}/return", json={"reason": "Không phải của tôi"}, headers=stranger).status_code == 404


def test_refund_cancelled_paid_order(client, admin, user, product):
    oid = client.post("/orders", json=order_body(product, payment_method="bank"), headers=user)
    oid = oid.json()["id"] if oid.status_code == 201 else client.post("/orders", json=order_body(product), headers=user).json()["id"]
    client.put(f"/admin/orders/{oid}/paid", headers=admin)
    assert client.post(f"/admin/orders/{oid}/refund", json={}, headers=admin).status_code == 400
    client.put(f"/admin/orders/{oid}/status", json={"status": "cancelled"}, headers=admin)
    assert client.post(f"/admin/orders/{oid}/refund", json={"amount": 1000}, headers=admin).json()["refund_amount"] == 1000


def test_refresh_token_rotation(client):
    client.post("/register", json={"email": "rt@x.com", "password": "secret123"})
    session = client.post("/login", data={"username": "rt@x.com", "password": "secret123"}).json()
    assert session["refresh_token"]
    new = client.post("/refresh", json={"refresh_token": session["refresh_token"]})
    assert new.status_code == 200
    fresh = new.json()
    me = client.get("/me", headers={"Authorization": f"Bearer {fresh['access_token']}"})
    assert me.status_code == 200
    # Token cũ đã xoay vòng: dùng lại bị từ chối và cả chuỗi bị thu hồi
    assert client.post("/refresh", json={"refresh_token": session["refresh_token"]}).status_code == 401
    assert client.post("/refresh", json={"refresh_token": fresh["refresh_token"]}).status_code == 401


def test_logout_revokes_refresh_token(client):
    client.post("/register", json={"email": "lo@x.com", "password": "secret123"})
    s = client.post("/login", data={"username": "lo@x.com", "password": "secret123"}).json()
    assert client.post("/logout", json={"refresh_token": s["refresh_token"]}).status_code == 200
    assert client.post("/refresh", json={"refresh_token": s["refresh_token"]}).status_code == 401


def test_email_verification_flow(client, monkeypatch):
    import routers.auth as auth

    sent = {}
    monkeypatch.setattr(auth, "is_mailtrap_configured", lambda: True)
    monkeypatch.setattr(auth, "send_email_verification_otp", lambda to, otp: sent.update(otp=otp))
    monkeypatch.setattr(auth, "REQUIRE_EMAIL_VERIFICATION", True)

    r = client.post("/register", json={"email": "ver@x.com", "password": "secret123"})
    assert r.json()["verification_required"] is True and sent["otp"]
    assert client.post("/login", data={"username": "ver@x.com", "password": "secret123"}).status_code == 403
    assert client.post("/verify-email", json={"email": "ver@x.com", "otp": "000000"}).status_code == 400
    ok = client.post("/verify-email", json={"email": "ver@x.com", "otp": sent["otp"]})
    assert ok.status_code == 200 and ok.json()["refresh_token"]
    assert client.post("/login", data={"username": "ver@x.com", "password": "secret123"}).status_code == 200
