from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session, selectinload

from dependencies import get_current_user, get_db
from models import Order, OrderItem, Product, Review, User
from schemas import ReviewCreate

router = APIRouter(tags=["Reviews"])


def _mask_name(user: User) -> str:
    # Chỉ hiện tên, không lộ email của người đánh giá
    name = (user.full_name or "").strip()
    return name or "Khách hàng"


def _review_response(review: Review):
    return {
        "id": review.id,
        "user_name": _mask_name(review.user),
        "rating": review.rating,
        "comment": review.comment,
        "created_at": review.created_at.isoformat(),
    }


def _has_purchased(db: Session, user_id: int, product_id: int) -> bool:
    return (
        db.query(OrderItem.id)
        .join(Order, Order.id == OrderItem.order_id)
        .filter(
            Order.user_id == user_id,
            Order.status == "completed",
            OrderItem.product_id == product_id,
        )
        .first()
        is not None
    )


def _get_product(db: Session, product_id: int) -> Product:
    product = (
        db.query(Product)
        .filter(Product.id == product_id, Product.is_active == True)
        .first()
    )
    if not product:
        raise HTTPException(status_code=404, detail="Không tìm thấy sản phẩm")
    return product


@router.get("/products/{product_id}/reviews")
def list_reviews(product_id: int, db: Session = Depends(get_db)):
    _get_product(db, product_id)
    reviews = (
        db.query(Review)
        .options(selectinload(Review.user))
        .filter(Review.product_id == product_id)
        .order_by(Review.created_at.desc())
        .limit(100)
        .all()
    )
    counts = dict(
        db.query(Review.rating, func.count(Review.id))
        .filter(Review.product_id == product_id)
        .group_by(Review.rating)
        .all()
    )
    total = sum(counts.values())
    average = (
        sum(star * count for star, count in counts.items()) / total if total else None
    )
    return {
        "average": round(average, 1) if average else None,
        "count": total,
        "distribution": {str(star): counts.get(star, 0) for star in range(1, 6)},
        "reviews": [_review_response(review) for review in reviews],
    }


@router.get("/products/{product_id}/reviews/me")
def my_review_status(
    product_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Người dùng đã được đánh giá chưa, và đánh giá hiện có của họ (nếu có)."""
    _get_product(db, product_id)
    review = (
        db.query(Review)
        .options(selectinload(Review.user))
        .filter(Review.product_id == product_id, Review.user_id == current_user.id)
        .first()
    )
    return {
        "can_review": _has_purchased(db, current_user.id, product_id),
        "review": _review_response(review) if review else None,
    }


@router.post("/products/{product_id}/reviews")
def save_review(
    product_id: int,
    data: ReviewCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Tạo hoặc sửa đánh giá; chỉ người đã nhận hàng (đơn hoàn thành) mới được đánh giá."""
    _get_product(db, product_id)
    if not _has_purchased(db, current_user.id, product_id):
        raise HTTPException(
            status_code=403,
            detail="Bạn chỉ có thể đánh giá sản phẩm sau khi đã nhận hàng",
        )

    comment = data.comment.strip() if data.comment else None
    review = (
        db.query(Review)
        .filter(Review.product_id == product_id, Review.user_id == current_user.id)
        .first()
    )
    if review:
        review.rating = data.rating
        review.comment = comment or None
        review.updated_at = datetime.utcnow()
    else:
        review = Review(
            product_id=product_id,
            user_id=current_user.id,
            rating=data.rating,
            comment=comment or None,
        )
        db.add(review)
    db.commit()
    db.refresh(review)
    return _review_response(review)


@router.delete("/products/{product_id}/reviews/me")
def delete_my_review(
    product_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    deleted = (
        db.query(Review)
        .filter(Review.product_id == product_id, Review.user_id == current_user.id)
        .delete()
    )
    if not deleted:
        raise HTTPException(status_code=404, detail="Bạn chưa đánh giá sản phẩm này")
    db.commit()
    return {"message": "Đã xóa đánh giá"}


@router.delete("/admin/reviews/{review_id}")
def admin_delete_review(
    review_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Bạn không có quyền Admin")
    deleted = db.query(Review).filter(Review.id == review_id).delete()
    if not deleted:
        raise HTTPException(status_code=404, detail="Không tìm thấy đánh giá")
    db.commit()
    return {"message": "Đã xóa đánh giá"}
