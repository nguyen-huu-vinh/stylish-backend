import hashlib
import hmac
import logging
import secrets
from datetime import datetime, timedelta

import requests
from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import func
from sqlalchemy.orm import Session

from config import GOOGLE_CLIENT_IDS, SECRET_KEY
from dependencies import get_db, get_current_user
from mailtrap import is_mailtrap_configured, send_password_reset_otp
from models import PasswordResetOTP, User
from schemas import (
    ForgotPasswordRequest,
    GoogleLogin,
    PasswordChange,
    ResetPasswordRequest,
    UserProfileUpdate,
    UserRegister,
)
from ratelimit import rate_limit
from security import (
    check_password_strength,
    create_access_token,
    get_password_hash,
    normalize_email,
    verify_password,
)

router = APIRouter(tags=["Auth"])
logger = logging.getLogger(__name__)


def _hash_reset_otp(user_id: int, otp: str) -> str:
    message = f"{user_id}:{otp}".encode()
    return hmac.new(SECRET_KEY.encode(), message, hashlib.sha256).hexdigest()


@router.post(
    "/register",
    status_code=201,
    dependencies=[Depends(rate_limit("register", 10, 3600))],
)
def register(user_data: UserRegister, db: Session = Depends(get_db)):
    email = normalize_email(user_data.email)
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="Email không hợp lệ")
    if db.query(User).filter(func.lower(User.email) == email).first():
        raise HTTPException(status_code=400, detail="Email này đã được sử dụng!")
    check_password_strength(user_data.password)

    new_user = User(
        email=email,
        hashed_password=get_password_hash(user_data.password),
        full_name=user_data.full_name,
        is_admin=False,
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return {"message": "Đăng ký tài khoản thành công!", "user_id": new_user.id}


@router.post("/login", dependencies=[Depends(rate_limit("login", 10, 60))])
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = (
        db.query(User)
        .filter(func.lower(User.email) == normalize_email(form_data.username))
        .first()
    )
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=400, detail="Email hoặc mật khẩu không chính xác")

    access_token = create_access_token(data={"sub": user.email})
    return {"access_token": access_token, "token_type": "bearer", "is_admin": user.is_admin}


@router.post("/login/google", dependencies=[Depends(rate_limit("google", 20, 60))])
def login_google(data: GoogleLogin, db: Session = Depends(get_db)):
    """Đăng nhập bằng Google: app gửi ID token, server nhờ Google xác minh."""
    if not GOOGLE_CLIENT_IDS:
        raise HTTPException(status_code=503, detail="Đăng nhập Google chưa được bật")
    try:
        res = requests.get(
            "https://oauth2.googleapis.com/tokeninfo",
            params={"id_token": data.id_token},
            timeout=10,
        )
    except requests.RequestException:
        raise HTTPException(status_code=502, detail="Không kết nối được tới Google")
    if res.status_code != 200:
        raise HTTPException(status_code=401, detail="Phiên đăng nhập Google không hợp lệ")

    info = res.json()
    # Token phải cấp cho chính app này, không phải app khác
    if info.get("aud") not in GOOGLE_CLIENT_IDS:
        raise HTTPException(status_code=401, detail="Phiên đăng nhập Google không hợp lệ")
    email = (info.get("email") or "").strip().lower()
    # Chỉ gộp vào tài khoản có sẵn khi Google đã xác minh email, tránh bị
    # chiếm tài khoản bằng một email Google chưa xác minh
    if not email or str(info.get("email_verified")).lower() != "true":
        raise HTTPException(status_code=401, detail="Email Google chưa được xác minh")

    user = db.query(User).filter(func.lower(User.email) == email).first()
    if not user:
        user = User(
            email=email,
            # Mật khẩu ngẫu nhiên không ai biết: chỉ vào được qua Google hoặc
            # "Quên mật khẩu"
            hashed_password=get_password_hash(secrets.token_urlsafe(32)),
            full_name=info.get("name"),
            is_admin=False,
        )
        db.add(user)
        db.commit()
        db.refresh(user)

    access_token = create_access_token(data={"sub": user.email})
    return {"access_token": access_token, "token_type": "bearer", "is_admin": user.is_admin}


def avatar_url(user: User):
    return f"/avatars/{user.avatar.key}" if user.avatar else None


@router.get("/me")
def get_me(current_user: User = Depends(get_current_user)):
    return {
        "id": current_user.id,
        "email": current_user.email,
        "full_name": current_user.full_name,
        "is_admin": current_user.is_admin,
        "avatar_url": avatar_url(current_user),
    }


@router.put("/me")
def update_me(
    profile_data: UserProfileUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    updates = profile_data.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=422, detail="Không có thông tin cần cập nhật")

    if "full_name" in updates:
        full_name = updates["full_name"]
        if full_name is not None:
            full_name = full_name.strip()
            if not full_name:
                raise HTTPException(status_code=422, detail="Họ tên không được để trống")
        current_user.full_name = full_name

    new_token = None
    if "email" in updates:
        email = (updates["email"] or "").strip().lower()
        if not email or "@" not in email:
            raise HTTPException(status_code=422, detail="Email không hợp lệ")
        existing = db.query(User).filter(User.email == email, User.id != current_user.id).first()
        if existing:
            raise HTTPException(status_code=409, detail="Email này đã được sử dụng")
        if email != current_user.email:
            current_user.email = email
            new_token = create_access_token(data={"sub": email})

    db.commit()
    db.refresh(current_user)
    return {
        "id": current_user.id,
        "email": current_user.email,
        "full_name": current_user.full_name,
        "is_admin": current_user.is_admin,
        "avatar_url": avatar_url(current_user),
        "access_token": new_token,
        "token_type": "bearer" if new_token else None,
    }


@router.post("/change-password")
def change_password(
    password_data: PasswordChange,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not verify_password(password_data.current_password, current_user.hashed_password):
        raise HTTPException(status_code=400, detail="Mật khẩu hiện tại không chính xác")
    check_password_strength(password_data.new_password)

    current_user.hashed_password = get_password_hash(password_data.new_password)
    db.commit()
    return {"message": "Đổi mật khẩu thành công"}


@router.post(
    "/forgot-password",
    dependencies=[Depends(rate_limit("forgot", 5, 600))],
)
def forgot_password(request: ForgotPasswordRequest, db: Session = Depends(get_db)):
    if not is_mailtrap_configured():
        raise HTTPException(status_code=503, detail="Mailtrap chưa được cấu hình")

    message = "Nếu email đã đăng ký, mã OTP sẽ được gửi đến email đó."
    user = (
        db.query(User)
        .filter(func.lower(User.email) == normalize_email(request.email))
        .first()
    )
    if user is None:
        # Trả cùng một thông báo để không lộ email nào đã đăng ký
        return {"message": message}

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


@router.post(
    "/reset-password",
    dependencies=[Depends(rate_limit("reset", 10, 600))],
)
def reset_password(request: ResetPasswordRequest, db: Session = Depends(get_db)):
    check_password_strength(request.new_password)

    user = (
        db.query(User)
        .filter(func.lower(User.email) == normalize_email(request.email))
        .first()
    )
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