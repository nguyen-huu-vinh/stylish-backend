from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from dependencies import get_db, get_current_admin
from models import Category, Product, User
from schemas import ProductSchema

router = APIRouter(tags=["Products"])


def _product_response(product: Product):
    return {
        "id": product.id,
        "name": product.name,
        "price": product.price,
        "discount_price": product.discount_price,
        "description": product.description,
        "is_sale": product.is_sale,
        "is_deal_of_the_day": product.is_deal_of_the_day,
        "is_new": product.is_new,
        "image_url": product.image_url,
        "is_trending": product.is_trending,
        "category_id": product.category_id,
        "category": product.category_ref.name if product.category_ref else None,
    }


@router.get("/products")
def get_products(
    category: Optional[str] = None,
    db: Session = Depends(get_db),
):
    query = db.query(Product)
    if category is not None:
        query = query.join(Product.category_ref).filter(
            func.lower(Category.name) == category.strip().lower()
        )
    return [_product_response(product) for product in query.all()]


@router.get("/trending")
def get_trending_products(db: Session = Depends(get_db)):
    products = db.query(Product).filter(Product.is_trending == True).all()
    return [_product_response(product) for product in products]


@router.get("/sale")
def get_sale_products(db: Session = Depends(get_db)):
    products = db.query(Product).filter(
        (Product.is_sale == True)
        | (
            (Product.discount_price.isnot(None))
            & (Product.discount_price < Product.price)
        )
    ).all()
    return [_product_response(product) for product in products]


@router.get("/deals-of-the-day")
def get_deals_of_the_day(db: Session = Depends(get_db)):
    products = db.query(Product).filter(Product.is_deal_of_the_day == True).all()
    return [_product_response(product) for product in products]


@router.get("/new-arrivals")
def get_new_products(db: Session = Depends(get_db)):
    products = db.query(Product).filter(Product.is_new == True).all()
    return [_product_response(product) for product in products]


@router.get("/products/{product_id}")
def get_product_detail(product_id: int, db: Session = Depends(get_db)):
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Không tìm thấy sản phẩm")
    return _product_response(product)


@router.post("/products")
def create_product(product: ProductSchema, db: Session = Depends(get_db),
                   current_admin: User = Depends(get_current_admin)):
    if not db.query(Category).filter(Category.id == product.category_id).first():
        raise HTTPException(status_code=404, detail="Không tìm thấy danh mục")
    new_p = Product(**product.model_dump())
    db.add(new_p)
    db.commit()
    db.refresh(new_p)
    return _product_response(new_p)


@router.put("/products/{product_id}")
def update_product(
    product_id: int,
    product_data: ProductSchema,
    db: Session = Depends(get_db),
    current_admin: User = Depends(get_current_admin),
):
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Không tìm thấy sản phẩm")
    if not db.query(Category).filter(Category.id == product_data.category_id).first():
        raise HTTPException(status_code=404, detail="Không tìm thấy danh mục")

    for field, value in product_data.model_dump().items():
        setattr(product, field, value)
    db.commit()
    db.refresh(product)
    return _product_response(product)


@router.delete("/products/{product_id}")
def delete_product(product_id: int, db: Session = Depends(get_db),
                   current_admin: User = Depends(get_current_admin)):
    p = db.query(Product).filter(Product.id == product_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Không tìm thấy sản phẩm")
    db.delete(p)
    db.commit()
    return {"message": "Đã xóa sản phẩm"}