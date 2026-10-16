from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from dependencies import get_db, get_current_admin
from models import Category, Product, Review, User
from schemas import ProductSchema

router = APIRouter(tags=["Products"])

# Size dùng cho sản phẩm cũ chưa được admin nhập size riêng
DEFAULT_SIZES = ["S", "M", "L", "XL"]


def product_sizes(product: Product) -> list:
    if product.sizes is None:
        return list(DEFAULT_SIZES)
    return [size for size in product.sizes.split(",") if size]


def _product_fields(product: ProductSchema) -> dict:
    data = product.model_dump()
    sizes = data.pop("sizes")
    # Không gửi size thì giữ mặc định; gửi danh sách rỗng = không có size
    data["sizes"] = None if sizes is None else ",".join(sizes)
    return data


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
        "stock": product.stock,
        "in_stock": product.stock is None or product.stock > 0,
        "sizes": product_sizes(product),
        "rating": round(product.rating_avg, 1) if product.rating_avg else None,
        "rating_count": product.rating_count or 0,
    }


@router.get("/products")
def get_products(
    category: Optional[str] = None,
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    query = (
        db.query(Product)
        .options(joinedload(Product.category_ref))
        .filter(Product.is_active == True)
    )
    if category is not None:
        query = query.join(Product.category_ref).filter(
            func.lower(Category.name) == category.strip().lower()
        )
    products = query.order_by(Product.id).offset(offset).limit(limit).all()
    return [_product_response(product) for product in products]


@router.get("/trending")
def get_trending_products(db: Session = Depends(get_db)):
    products = db.query(Product).filter(Product.is_active == True, Product.is_trending == True).all()
    return [_product_response(product) for product in products]


@router.get("/sale")
def get_sale_products(db: Session = Depends(get_db)):
    products = db.query(Product).filter(
        Product.is_active == True,
        (Product.is_sale == True)
        | (
            (Product.discount_price.isnot(None))
            & (Product.discount_price < Product.price)
        )
    ).all()
    return [_product_response(product) for product in products]


@router.get("/deals-of-the-day")
def get_deals_of_the_day(db: Session = Depends(get_db)):
    products = db.query(Product).filter(Product.is_active == True, Product.is_deal_of_the_day == True).all()
    return [_product_response(product) for product in products]


@router.get("/new-arrivals")
def get_new_products(db: Session = Depends(get_db)):
    products = db.query(Product).filter(Product.is_active == True, Product.is_new == True).all()
    return [_product_response(product) for product in products]


@router.get("/products/{product_id}")
def get_product_detail(product_id: int, db: Session = Depends(get_db)):
    product = (
        db.query(Product)
        .filter(Product.id == product_id, Product.is_active == True)
        .first()
    )
    if not product:
        raise HTTPException(status_code=404, detail="Không tìm thấy sản phẩm")
    return _product_response(product)


@router.post("/products")
def create_product(product: ProductSchema, db: Session = Depends(get_db),
                   current_admin: User = Depends(get_current_admin)):
    if not db.query(Category).filter(Category.id == product.category_id).first():
        raise HTTPException(status_code=404, detail="Không tìm thấy danh mục")
    new_p = Product(**_product_fields(product))
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

    for field, value in _product_fields(product_data).items():
        setattr(product, field, value)
    db.commit()
    db.refresh(product)
    return _product_response(product)


@router.delete("/products/{product_id}")
def delete_product(product_id: int, db: Session = Depends(get_db),
                   current_admin: User = Depends(get_current_admin)):
    p = db.query(Product).filter(
        Product.id == product_id, Product.is_active == True
    ).first()
    if not p:
        raise HTTPException(status_code=404, detail="Không tìm thấy sản phẩm")
    # Xóa mềm: giữ lại dòng để đơn cũ và đánh giá không bị mồ côi
    p.is_active = False
    db.commit()
    return {"message": "Đã xóa sản phẩm"}