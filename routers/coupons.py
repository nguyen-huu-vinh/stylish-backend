from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from dependencies import get_current_admin, get_current_user, get_db
from models import Coupon, Order, User
from schemas import CouponCreate, CouponValidate

router = APIRouter(tags=["Coupons"])


def _coupon_response(coupon: Coupon):
    return {
        "id": coupon.id,
        "code": coupon.code,
        "description": coupon.description,
        "discount_type": coupon.discount_type,
        "value": coupon.value,
        "min_order": coupon.min_order,
        "max_discount": coupon.max_discount,
        "usage_limit": coupon.usage_limit,
        "used_count": coupon.used_count,
        "expires_at": coupon.expires_at.isoformat() if coupon.expires_at else None,
        "is_active": coupon.is_active,
    }


def calculate_discount(
    db: Session,
    code: str,
    subtotal: float,
    user: User,
    lock: bool = False,
):
    """Kiểm tra mã và tính số tiền giảm; trả về (coupon, discount) hoặc báo lỗi 400.

    lock=True khóa dòng mã (PostgreSQL) để hai đơn cùng lúc không vượt giới hạn.
    """
    query = db.query(Coupon).filter(Coupon.code == code.strip().upper())
    if lock:
        query = query.with_for_update()
    coupon = query.first()
    if not coupon or not coupon.is_active:
        raise HTTPException(status_code=400, detail="Mã giảm giá không hợp lệ")
    if coupon.expires_at and coupon.expires_at < datetime.utcnow():
        raise HTTPException(status_code=400, detail="Mã giảm giá đã hết hạn")
    if coupon.usage_limit is not None and coupon.used_count >= coupon.usage_limit:
        raise HTTPException(status_code=400, detail="Mã giảm giá đã hết lượt sử dụng")
    if subtotal < coupon.min_order:
        raise HTTPException(
            status_code=400,
            detail=f"Đơn hàng tối thiểu {coupon.min_order:,.0f}đ để dùng mã này",
        )
    already_used = (
        db.query(Order.id)
        .filter(
            Order.user_id == user.id,
            Order.coupon_code == coupon.code,
            Order.status != "cancelled",
        )
        .first()
    )
    if already_used:
        raise HTTPException(status_code=400, detail="Bạn đã sử dụng mã giảm giá này rồi")

    if coupon.discount_type == "percent":
        discount = subtotal * coupon.value / 100
        if coupon.max_discount is not None:
            discount = min(discount, coupon.max_discount)
    else:
        discount = coupon.value
    # Làm tròn đồng và không giảm quá giá trị đơn
    return coupon, float(min(round(discount), subtotal))


def release_coupon(db: Session, order: Order) -> None:
    """Trả lại một lượt dùng mã khi đơn bị hủy."""
    if not order.coupon_code:
        return
    coupon = db.query(Coupon).filter(Coupon.code == order.coupon_code).first()
    if coupon and coupon.used_count > 0:
        coupon.used_count -= 1


def reuse_coupon(db: Session, order: Order) -> None:
    """Tính lại một lượt dùng mã khi admin mở lại đơn đã hủy."""
    if not order.coupon_code:
        return
    coupon = db.query(Coupon).filter(Coupon.code == order.coupon_code).first()
    if coupon:
        coupon.used_count += 1


@router.post("/coupons/validate")
def validate_coupon(
    data: CouponValidate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    coupon, discount = calculate_discount(db, data.code, data.subtotal, current_user)
    return {
        "code": coupon.code,
        "description": coupon.description,
        "discount": discount,
        "total": data.subtotal - discount,
    }


@router.get("/admin/coupons")
def list_coupons(
    db: Session = Depends(get_db),
    current_admin: User = Depends(get_current_admin),
):
    return [
        _coupon_response(coupon)
        for coupon in db.query(Coupon).order_by(Coupon.id.desc()).all()
    ]


@router.post("/admin/coupons", status_code=201)
def create_coupon(
    data: CouponCreate,
    db: Session = Depends(get_db),
    current_admin: User = Depends(get_current_admin),
):
    code = data.code.upper()
    if db.query(Coupon).filter(Coupon.code == code).first():
        raise HTTPException(status_code=400, detail="Mã giảm giá đã tồn tại")
    coupon = Coupon(**{**data.model_dump(), "code": code})
    db.add(coupon)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="Mã giảm giá đã tồn tại")
    db.refresh(coupon)
    return _coupon_response(coupon)


@router.put("/admin/coupons/{coupon_id}")
def update_coupon(
    coupon_id: int,
    data: CouponCreate,
    db: Session = Depends(get_db),
    current_admin: User = Depends(get_current_admin),
):
    coupon = db.query(Coupon).filter(Coupon.id == coupon_id).first()
    if not coupon:
        raise HTTPException(status_code=404, detail="Không tìm thấy mã giảm giá")
    code = data.code.upper()
    clash = db.query(Coupon).filter(Coupon.code == code, Coupon.id != coupon_id).first()
    if clash:
        raise HTTPException(status_code=400, detail="Mã giảm giá đã tồn tại")
    for field, value in {**data.model_dump(), "code": code}.items():
        setattr(coupon, field, value)
    db.commit()
    db.refresh(coupon)
    return _coupon_response(coupon)


@router.delete("/admin/coupons/{coupon_id}")
def delete_coupon(
    coupon_id: int,
    db: Session = Depends(get_db),
    current_admin: User = Depends(get_current_admin),
):
    # Đơn cũ giữ nguyên coupon_code dạng chữ nên xóa mã không ảnh hưởng đơn đã đặt
    deleted = db.query(Coupon).filter(Coupon.id == coupon_id).delete()
    if not deleted:
        raise HTTPException(status_code=404, detail="Không tìm thấy mã giảm giá")
    db.commit()
    return {"message": "Đã xóa mã giảm giá"}
