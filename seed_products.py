import csv
import os
import requests

BASE_URL = os.getenv("BASE_URL", "http://127.0.0.1:8000")
print("Đang seed vào:", BASE_URL)

# Đặt trước khi chạy:
#   export ADMIN_EMAIL="..."  ADMIN_PASSWORD="..."
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD")
if not ADMIN_EMAIL or not ADMIN_PASSWORD:
    raise SystemExit("Thiếu ADMIN_EMAIL / ADMIN_PASSWORD")

# 1. Đăng nhập lấy token (/login nhận form data, field tên "username")
# timeout dài vì Render free có thể đang "ngủ", request đầu mất ~30-60s
res = requests.post(
    f"{BASE_URL}/login",
    data={"username": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
    timeout=90,
)
res.raise_for_status()
headers = {"Authorization": f"Bearer {res.json()['access_token']}"}
categories_response = requests.get(f"{BASE_URL}/categories", timeout=30)
categories_response.raise_for_status()
category_ids = {
    category["name"].casefold(): category["id"]
    for category in categories_response.json()
}

# 2. Seed sản phẩm
with open("products.csv", encoding="utf-8") as f:
    for row in csv.DictReader(f):
        payload = {
            "name": row["name"],
            "price": float(row["price"]),
            "image_url": row["image_url"],
            "description": row.get("description", "").strip() or None,
            "discount_price": (
                float(row["discount_price"])
                if row.get("discount_price", "").strip()
                else None
            ),
            "is_sale": row.get("is_sale", "false").strip().lower() == "true",
            "is_trending": row["is_trending"].strip().lower() == "true",
            "is_new": row.get("is_new", "false").strip().lower() == "true",
            "category_id": category_ids[row["category"].strip().casefold()],
        }
        r = requests.post(f"{BASE_URL}/products", json=payload,
                          headers=headers, timeout=30)
        print(row["name"], "→", r.status_code)
        if r.status_code >= 400:
            print("   ", r.text)