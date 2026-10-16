from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from dependencies import get_db, get_current_admin
from models import Address, Review, User
from schemas import UserRegister, UserUpdate
from security import check_password_strength, get_password_hash, normalize_email

router = APIRouter(prefix="/users", tags=["Users"])


@router.get("")
def get_all_users(db: Session = Depends(get_db), current_admin: User = Depends(get_current_admin)):
    return [
        {
            "id": u.id,
            "email": u.email,
            "full_name": u.full_name,
            "is_admin": u.is_admin,
        }
        for u in db.query(User).all()
    ]


@router.post("")
def create_user_by_admin(user_data: UserRegister, db: Session = Depends(get_db),
                         current_admin: User = Depends(get_current_admin)):
    if db.query(User).filter(
        func.lower(User.email) == normalize_email(user_data.email)
    ).first():
        raise HTTPException(status_code=400, detail="Email đã tồn tại!")
    check_password_strength(user_data.password)

    user = User(
        email=normalize_email(user_data.email),
        hashed_password=get_password_hash(user_data.password),
        full_name=user_data.full_name,
        is_admin=False,
    )
    db.add(user)
    db.commit()
    return {"message": "Thêm người dùng thành công"}


@router.put("/{user_id}")
def update_user(user_id: int, user_data: UserUpdate, db: Session = Depends(get_db),
                current_admin: User = Depends(get_current_admin)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Không tìm thấy tài khoản")

    if user_data.email is not None and user_data.email != user.email:
        if db.query(User).filter(User.email == user_data.email).first():
            raise HTTPException(status_code=400, detail="Email này đã được người khác sử dụng!")
        user.email = user_data.email

    if user_data.full_name is not None:
        user.full_name = user_data.full_name
    if user_data.is_admin is not None:
        user.is_admin = user_data.is_admin
    if user_data.password is not None:
        check_password_strength(user_data.password)
        user.hashed_password = get_password_hash(user_data.password)

    db.commit()
    return {"message": "Cập nhật tài khoản thành công"}


@router.delete("/{user_id}")
def delete_user(user_id: int, db: Session = Depends(get_db),
                current_admin: User = Depends(get_current_admin)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Không tìm thấy tài khoản")
    if user.id == current_admin.id:
        raise HTTPException(status_code=400, detail="Không thể xóa tài khoản Admin đang đăng nhập!")

    db.query(Review).filter(Review.user_id == user.id).delete()
    db.query(Address).filter(Address.user_id == user.id).delete()
    db.delete(user)
    db.commit()
    return {"message": "Đã xóa tài khoản thành công"}