import hashlib
import hmac
import logging
import secrets
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from config import SECRET_KEY
from dependencies import get_db, get_current_user
from mailtrap import is_mailtrap_configured, send_password_reset_otp
from models import PasswordResetOTP, User
from schemas import ForgotPasswordRequest, PasswordChange, ResetPasswordRequest, UserRegister
from security import verify_password, get_password_hash, create_access_token

router = APIRouter(tags=["Auth"])
logger = logging.getLogger(__name__)


def _hash_reset_otp(user_id: int, otp: str) -> str:
    message = f"{user_id}:{otp}".encode()
    return hmac.new(SECRET_KEY.encode(), message, hashlib.sha256).hexdigest()


@router.post("/register", status_code=201)
def register(user_data: UserRegister, db: Session = Depends(get_db)):
    if db.query(User).filter(User.email == user_data.email).first():
        raise HTTPException(status_code=400, detail="Email này đã được sử dụng!")
    if len(user_data.password) < 6:
        raise HTTPException(status_code=400, detail="Mật khẩu phải có ít nhất 6 ký tự!")

    new_user = User(
        email=user_data.email,
        hashed_password=get_password_hash(user_data.password),
        full_name=user_data.full_name,
        is_admin=False,
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return {"message": "Đăng ký tài khoản thành công!", "user_id": new_user.id}


@router.post("/login")
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == form_data.username).first()
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=400, detail="Email hoặc mật khẩu không chính xác")

    access_token = create_access_token(data={"sub": user.email})
    return {"access_token": access_token, "token_type": "bearer", "is_admin": user.is_admin}


@router.get("/me")
def get_me(current_user: User = Depends(get_current_user)):
    return {
        "id": current_user.id,
        "email": current_user.email,
        "full_name": current_user.full_name,
        "is_admin": current_user.is_admin,
    }


@router.post("/change-password")
def change_password(
    password_data: PasswordChange,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not verify_password(password_data.current_password, current_user.hashed_password):
        raise HTTPException(status_code=400, detail="Mật khẩu hiện tại không chính xác")
    if len(password_data.new_password) < 6:
        raise HTTPException(status_code=400, detail="Mật khẩu mới phải có ít nhất 6 ký tự!")

    current_user.hashed_password = get_password_hash(password_data.new_password)
    db.commit()
    return {"message": "Đổi mật khẩu thành công"}


@router.post("/forgot-password")
def forgot_password(request: ForgotPasswordRequest, db: Session = Depends(get_db)):
    if not is_mailtrap_configured():
        raise HTTPException(status_code=503, detail="Mailtrap chưa được cấu hình")

    message = "Nếu email đã đăng ký, mã OTP sẽ được gửi đến email đó."
    user = db.query(User).filter(User.email == request.email).first()
    if user is None:
        raise HTTPException(status_code=404, detail="Email chưa được đăng ký")

    now = datetime.utcnow()
    reset_record = (
        db.query(PasswordResetOTP)
        .filter(PasswordResetOTP.user_id == user.id)
        .first()
    )
    if reset_record and reset_record.created_at > now - timedelta(seconds=60):
        return {"message": message}

    otp = f"{secrets.randbelow(1_000_000):06d}"
    if reset_record:
        reset_record.otp_hash = _hash_reset_otp(user.id, otp)
        reset_record.created_at = now
        reset_record.expires_at = now + timedelta(minutes=10)
        reset_record.attempts = 0
    else:
        reset_record = PasswordResetOTP(
            user_id=user.id,
            otp_hash=_hash_reset_otp(user.id, otp),
            created_at=now,
            expires_at=now + timedelta(minutes=10),
            attempts=0,
        )
        db.add(reset_record)
    db.commit()

    try:
        send_password_reset_otp(user.email, otp)
    except Exception:
        logger.exception("Unable to send password reset OTP through Mailtrap")
        db.delete(reset_record)
        db.commit()
        raise HTTPException(
            status_code=503,
            detail="Không thể gửi OTP lúc này. Vui lòng thử lại sau.",
        )

    return {"message": message}


@router.post("/reset-password")
def reset_password(request: ResetPasswordRequest, db: Session = Depends(get_db)):
    if len(request.new_password) < 6:
        raise HTTPException(status_code=400, detail="Mật khẩu mới phải có ít nhất 6 ký tự!")

    user = db.query(User).filter(User.email == request.email).first()
    reset_record = None
    if user:
        reset_record = (
            db.query(PasswordResetOTP)
            .filter(PasswordResetOTP.user_id == user.id)
            .first()
        )

    now = datetime.utcnow()
    invalid_otp = HTTPException(status_code=400, detail="OTP không hợp lệ hoặc đã hết hạn")
    if (
        user is None
        or reset_record is None
        or reset_record.expires_at <= now
        or reset_record.attempts >= 5
    ):
        if reset_record:
            db.delete(reset_record)
            db.commit()
        raise invalid_otp

    submitted_hash = _hash_reset_otp(user.id, request.otp)
    if not hmac.compare_digest(submitted_hash, reset_record.otp_hash):
        reset_record.attempts += 1
        if reset_record.attempts >= 5:
            db.delete(reset_record)
        db.commit()
        raise invalid_otp

    user.hashed_password = get_password_hash(request.new_password)
    db.delete(reset_record)
    db.commit()
    return {"message": "Đặt lại mật khẩu thành công"}