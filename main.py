from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI()

# ----- Định nghĩa "hình dạng" của 1 sản phẩm -----
class Product(BaseModel):
    id: int
    name: str
    price: float
    image_url: str


# ----- Dữ liệu tạm, lưu trong RAM (chưa cần database) -----
products: list[Product] = [
    Product(id=1, name="Áo thun trắng", price=199000, image_url="https://example.com/1.jpg"),
    Product(id=2, name="Quần jeans", price=450000, image_url="https://example.com/2.jpg"),
]

trending_products: list[Product] = [
    Product(id=101, name="Váy hoa", price=320000, image_url="https://picsum.photos/id/3/300/300"),
    Product(id=102, name="Túi xách", price=280000, image_url="https://picsum.photos/id/4/300/300"),
]

@app.get("/trending")
def get_trending():
    return trending_products

# ----- GET: lấy toàn bộ danh sách sản phẩm -----
@app.get("/products")
def get_products():
    return products


# ----- GET: lấy 1 sản phẩm theo id -----
@app.get("/products/{product_id}")
def get_product(product_id: int):
    for p in products:
        if p.id == product_id:
            return p
    raise HTTPException(status_code=404, detail="Không tìm thấy sản phẩm")


# ----- POST: thêm sản phẩm mới -----
@app.post("/products")
def create_product(product: Product):
    products.append(product)
    return product


# ----- DELETE: xóa sản phẩm theo id -----
@app.delete("/products/{product_id}")
def delete_product(product_id: int):
    for p in products:
        if p.id == product_id:
            products.remove(p)
            return {"message": "Đã xóa sản phẩm"}
    raise HTTPException(status_code=404, detail="Không tìm thấy sản phẩm")