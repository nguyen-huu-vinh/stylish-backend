import csv
import getpass
import os

import requests

BASE_URL = "https://stylish-backend-lyrx.onrender.com"

# Lấy thông tin admin từ biến môi trường, nếu không có thì hỏi khi chạy
email = os.getenv("ADMIN_EMAIL") or input("Admin email: ")
password = os.getenv("ADMIN_PASSWORD") or getpass.getpass("Admin password: ")

# 1. Đăng nhập để lấy token (Render free có thể mất ~50s để "thức dậy")
login = requests.post(
    f"{BASE_URL}/login",
    data={"username": email, "password": password},  # form, không phải JSON
    timeout=90,
)
if login.status_code != 200:
    print("Đăng nhập thất bại:", login.status_code, login.text)
    raise SystemExit(1)

headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

# 2. Import sản phẩm từ CSV
with open("products.csv", encoding="utf-8") as f:
    reader = csv.DictReader(f)
    for row in reader:
        payload = {
            "name": row["name"],
            "price": float(row["price"]),
            "image_url": row["image_url"],
            "is_trending": row["is_trending"].strip().lower() == "true",
        }
        response = requests.post(
            f"{BASE_URL}/products",
            json=payload,
            headers=headers,
            timeout=30,
        )
        print(row["name"], "→", response.status_code)