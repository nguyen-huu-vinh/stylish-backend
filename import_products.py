import csv
import getpass
import os

import requests

BASE_URL = "https://stylish-backend-lyrx.onrender.com"

email = os.getenv("ADMIN_EMAIL") or input("Admin email: ")
password = os.getenv("ADMIN_PASSWORD") or getpass.getpass("Admin password: ")

# 1. Đăng nhập (Render free có thể mất ~50s để "thức dậy")
login = requests.post(
    f"{BASE_URL}/login",
    data={"username": email, "password": password},  # form, không phải JSON
    timeout=90,
)
if login.status_code != 200:
    print("Đăng nhập thất bại:", login.status_code, login.text)
    raise SystemExit(1)

headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
categories_response = requests.get(f"{BASE_URL}/categories", timeout=30)
categories_response.raise_for_status()
category_ids = {
    category["name"].casefold(): category["id"]
    for category in categories_response.json()
}

# 2. Import sản phẩm từ CSV
ok, failed = 0, 0
with open("products.csv", encoding="utf-8") as f:
    reader = csv.DictReader(f)
    for line_no, row in enumerate(reader, start=2):  # dòng 1 là header
        try:
            payload = {
                "name": row["name"].strip(),
                "price": float(row["price"]),
                "image_url": row["image_url"].strip(),
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
            if not payload["image_url"]:
                raise ValueError("thiếu image_url")
        except (KeyError, ValueError) as e:
            print(f"Dòng {line_no}: bỏ qua ({e})")
            failed += 1
            continue

        response = requests.post(
            f"{BASE_URL}/products",
            json=payload,
            headers=headers,
            timeout=30,
        )
        print(payload["name"], "→", response.status_code)
        if response.status_code >= 400:
            print("   ", response.text)
            failed += 1
        else:
            ok += 1

print(f"\nXong: {ok} thành công, {failed} lỗi")