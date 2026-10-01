from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from dependencies import get_db, get_current_admin
from models import Product, User
from schemas import ProductSchema

router = APIRouter(tags=["Products"])


@router.get("/products")
def get_products(db: Session = Depends(get_db)):
    return db.query(Product).all()


@router.get("/trending")
def get_trending_products(db: Session = Depends(get_db)):
    return db.query(Product).filter(Product.is_trending == True).all()


@router.get("/products/{product_id}")
def get_product_detail(product_id: int, db: Session = Depends(get_db)):
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Không tìm thấy sản phẩm")
    return product


@router.post("/products")
def create_product(product: ProductSchema, db: Session = Depends(get_db),
                   current_admin: User = Depends(get_current_admin)):
    new_p = Product(**product.model_dump())
    db.add(new_p)
    db.commit()
    db.refresh(new_p)
    return new_p


@router.delete("/products/{product_id}")
def delete_product(product_id: int, db: Session = Depends(get_db),
                   current_admin: User = Depends(get_current_admin)):
    p = db.query(Product).filter(Product.id == product_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Không tìm thấy sản phẩm")
    db.delete(p)
    db.commit()
    return {"message": "Đã xóa sản phẩm"}