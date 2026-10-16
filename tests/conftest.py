import os
import sys
import tempfile

# Phải đặt trước khi import app: dùng SQLite tạm, không đụng stylish.db
_tmp = tempfile.mkdtemp()
os.environ.pop("DATABASE_URL", None)
os.environ["SECRET_KEY"] = "test-secret"
os.environ["ADMIN_EMAIL"] = "Admin@Test.com"
os.environ["ADMIN_PASSWORD"] = "admin12345"
os.chdir(_tmp)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from fastapi.testclient import TestClient

import main
import ratelimit


@pytest.fixture(scope="session")
def client():
    with TestClient(main.app) as c:
        yield c


@pytest.fixture(autouse=True)
def _reset_rate_limit():
    ratelimit._hits.clear()


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    import routers.tracking as tracking

    monkeypatch.setattr(tracking, "_geocode", lambda address: (10.0, 106.0))


def login(client, email, password):
    r = client.post("/login", data={"username": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture(scope="session")
def admin(client):
    return login(client, "admin@test.com", "admin12345")


@pytest.fixture
def user(client):
    import uuid

    email = f"{uuid.uuid4().hex[:8]}@x.com"
    r = client.post("/register", json={"email": email, "password": "secret123"})
    assert r.status_code == 201
    return login(client, email, "secret123")


@pytest.fixture
def product(client, admin):
    cat = client.post("/categories", json={"name": f"c{__import__('uuid').uuid4().hex}"}, headers=admin)
    assert cat.status_code in (200, 201), cat.text
    r = client.post(
        "/products",
        json={
            "name": "Giày", "price": 100000, "image_url": "x",
            "category_id": cat.json()["id"], "stock": 3, "sizes": ["38"],
        },
        headers=admin,
    )
    assert r.status_code == 200, r.text
    return r.json()
