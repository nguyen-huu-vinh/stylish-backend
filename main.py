from fastapi import FastAPI, HTTPException, Depends
from sqlalchemy.orm import Session
from pydantic import BaseModel

from database import engine, SessionLocal, Base
from models import ProductDB

Base.metadata.create_all(bind=engine)

app = FastAPI()


class ProductCreate(BaseModel):
    name: str
    price: float
    image_url: str
    is_trending: bool = False


class ProductOut(ProductCreate):
    id: int

    class Config:
        from_attributes = True


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@app.on_event("startup")
def seed_data():
    db = SessionLocal()
    if db.query(ProductDB).count() == 0:
        db.add(ProductDB(name="Áo thun trắng", price=199000, image_url="https://picsum.photos/id/1/300/300", is_trending=False))
        db.add(ProductDB(name="Quần jeans", price=450000, image_url="https://picsum.photos/id/2/300/300", is_trending=False))
        db.add(ProductDB(name="Váy hoa", price=320000, image_url="https://picsum.photos/id/3/300/300", is_trending=True))
        db.add(ProductDB(name="Túi xách", price=280000, image_url="https://picsum.photos/id/4/300/300", is_trending=True))
        db.commit()
    db.close()


@app.get("/products", response_model=list[ProductOut])
def get_products(db: Session = Depends(get_db)):
    return db.query(ProductDB).filter(ProductDB.is_trending == False).all()


@app.get("/trending", response_model=list[ProductOut])
def get_trending(db: Session = Depends(get_db)):
    return db.query(ProductDB).filter(ProductDB.is_trending == True).all()


@app.get("/products/{product_id}", response_model=ProductOut)
def get_product(product_id: int, db: Session = Depends(get_db)):
    product = db.query(ProductDB).filter(ProductDB.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Không tìm thấy sản phẩm")
    return product


@app.post("/products", response_model=ProductOut)
def create_product(product: ProductCreate, db: Session = Depends(get_db)):
    new_product = ProductDB(**product.dict())
    db.add(new_product)
    db.commit()
    db.refresh(new_product)
    return new_product


@app.delete("/products/{product_id}")
def delete_product(product_id: int, db: Session = Depends(get_db)):
    product = db.query(ProductDB).filter(ProductDB.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Không tìm thấy sản phẩm")
    db.delete(product)
    db.commit()
    return {"message": "Đã xóa sản phẩm"}