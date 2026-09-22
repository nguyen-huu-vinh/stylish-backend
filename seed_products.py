import csv
import requests

API_URL = "https://stylish-backend-lyrx.onrender.com/products"

with open("products.csv", encoding="utf-8") as f:
    reader = csv.DictReader(f)
    for row in reader:
        payload = {
            "name": row["name"],
            "price": float(row["price"]),
            "image_url": row["image_url"],
            "is_trending": row["is_trending"].strip().lower() == "true"
        }
        response = requests.post(API_URL, json=payload)
        print(row["name"], "→", response.status_code)