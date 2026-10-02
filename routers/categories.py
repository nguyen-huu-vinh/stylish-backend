from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from dependencies import get_current_admin, get_db
from models import Category, Product, User
from schemas import CategoryCreate, CategoryUpdate

router = APIRouter(prefix="/categories", tags=["Categories"])


@router.get("")
def get_categories(db: Session = Depends(get_db)):
    return db.query(Category).order_by(Category.name).all()


@router.post("")
def create_category(
    category: CategoryCreate,
    db: Session = Depends(get_db),
    current_admin: User = Depends(get_current_admin),
):
    name = category.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Tên danh mục không được để trống")
    existing = db.query(Category).filter(func.lower(Category.name) == name.lower()).first()
    if existing:
        raise HTTPException(status_code=409, detail="Danh mục đã tồn tại")

    new_category = Category(name=name)
    db.add(new_category)
    db.commit()
    db.refresh(new_category)
    return new_category


@router.put("/{category_id}")
def update_category(
    category_id: int,
    category: CategoryUpdate,
    db: Session = Depends(get_db),
    current_admin: User = Depends(get_current_admin),
):
    current = db.query(Category).filter(Category.id == category_id).first()
    if not current:
        raise HTTPException(status_code=404, detail="Không tìm thấy danh mục")

    name = category.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Tên danh mục không được để trống")
    duplicate = db.query(Category).filter(
        func.lower(Category.name) == name.lower(), Category.id != category_id
    ).first()
    if duplicate:
        raise HTTPException(status_code=409, detail="Danh mục đã tồn tại")

    current.name = name
    db.commit()
    db.refresh(current)
    return current


@router.delete("/{category_id}")
def delete_category(
    category_id: int,
    db: Session = Depends(get_db),
    current_admin: User = Depends(get_current_admin),
):
    category = db.query(Category).filter(Category.id == category_id).first()
    if not category:
        raise HTTPException(status_code=404, detail="Không tìm thấy danh mục")
    if db.query(Product).filter(Product.category_id == category_id).first():
        raise HTTPException(
            status_code=409,
            detail="Không thể xóa danh mục đang có sản phẩm",
        )

    db.delete(category)
    db.commit()
    return {"message": "Đã xóa danh mục"}