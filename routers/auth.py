import hashlib
import hmac
import logging
import secrets
from datetime import datetime, timedelta
from timeutil import utcnow

import requests
from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import func
from sqlalchemy.orm import Session

from config import (
    GOOGLE_CLIENT_IDS,
    REFRESH_TOKEN_EXPIRE_DAYS,
    REQUIRE_EMAIL_VERIFICATION,
    SECRET_KEY,
)
from dependencies import get_db, get_current_user
from mailtrap import (
    is_mailtrap_configured,
    send_email_verification_otp,
    send_password_reset_otp,
)
from models import EmailVerificationOTP, PasswordResetOTP, RefreshToken, User
from schemas import (
    ForgotPasswordRequest,
    GoogleLogin,
    RefreshRequest,
    ResendVerificationRequest,
    VerifyEmailRequest,
    PasswordChange,
    ResetPasswordRequest,
    UserProfileUpdate,
    UserRegister,
)
from ratelimit import rate_limit
from security import (
    check_password_strength,
    issue_token,
    get_password_hash,
    hash_refresh_token,
    new_refresh_token,
    normalize_email,
    verify_password,
)

router = APIRouter(tags=["Auth"])
logger = logging.getLogger(__name__)


def _start_session(db: Session, user: User) -> dict:
    """Cấp access token + refresh token mới cho người dùng."""
    now = utcnow()
    # Dọn token hết hạn của user này để bảng không phình ra
    db.query(RefreshToken).filter(
        RefreshToken.user_id == user.id, RefreshToken.expires_at < now
    ).delete()
    refresh, refresh_hash = new_refresh_token()
    db.add(RefreshToken(
        user_id=user.id,
        token_hash=refresh_hash,
        expires_at=now + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS),
    ))
    db.commit()
    return {
        "access_token": issue_token(user),
        "refresh_token": refresh,
        "token_type": "bearer",
        "is_admin": user.is_admin,
    }


def _revoke_refresh_tokens(db: Session, user_id: int) -> None:
    db.query(RefreshToken).filter(
        RefreshToken.user_id == user_id, RefreshToken.revoked == False
    ).update({"revoked": True})


def _send_verification_otp(db: Session, user: User) -> bool:
    """Tạo và gửi OTP xác minh email. False nếu chưa gửi được (cooldown/lỗi mạng)."""
    now = utcnow()
    record = (
        db.query(EmailVerificationOTP)
        .filter(EmailVerificationOTP.user_id == user.id)
        .first()
    )
    if record and record.created_at > now - timedelta(seconds=60):
        return False
    otp = f"{secrets.randbelow(1_000_000):06d}"
    if record is None:
        record = EmailVerificationOTP(user_id=user.id)
        db.add(record)
    record.otp_hash = _hash_reset_otp(user.id, otp)
    record.created_at = now
    record.expires_at = now + timedelta(minutes=10)
    record.attempts = 0
    db.commit()
    try:
        send_email_verification_otp(user.email, otp)
    except Exception:
        logger.exception("Unable to send email verification OTP")
        return False
    return True


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
        # Chỉ đòi xác minh khi gửi được email OTP
        email_verified=not is_mailtrap_configured(),
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    needs_verification = not new_user.email_verified
    if needs_verification:
        _send_verification_otp(db, new_user)
    return {
        "message": "Đăng ký tài khoản thành công!",
        "user_id": new_user.id,
        "verification_required": needs_verification,
    }


@router.post("/login", dependencies=[Depends(rate_limit("login", 10, 60))])
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = (
        db.query(User)
        .filter(func.lower(User.email) == normalize_email(form_data.username))
        .first()
    )
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=400, detail="Email hoặc mật khẩu không chính xác")
    if REQUIRE_EMAIL_VERIFICATION and not user.email_verified:
        raise HTTPException(status_code=403, detail="Email chưa được xác minh")

    return _start_session(db, user)


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
            email_verified=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)

    return _start_session(db, user)


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
            new_token = issue_token(current_user)

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


@router.post(
    "/verify-email", dependencies=[Depends(rate_limit("verify", 10, 600))]
)
def verify_email(request: VerifyEmailRequest, db: Session = Depends(get_db)):
    user = (
        db.query(User)
        .filter(func.lower(User.email) == normalize_email(request.email))
        .first()
    )
    record = (
        db.query(EmailVerificationOTP)
        .filter(EmailVerificationOTP.user_id == user.id)
        .first()
        if user
        else None
    )
    invalid = HTTPException(status_code=400, detail="OTP không hợp lệ hoặc đã hết hạn")
    if record is None or record.expires_at <= utcnow() or record.attempts >= 5:
        if record:
            db.delete(record)
            db.commit()
        raise invalid
    if not hmac.compare_digest(
        _hash_reset_otp(user.id, request.otp), record.otp_hash
    ):
        record.attempts += 1
        if record.attempts >= 5:
            db.delete(record)
        db.commit()
        raise invalid
    user.email_verified = True
    db.delete(record)
    db.commit()
    return _start_session(db, user)


@router.post(
    "/resend-verification", dependencies=[Depends(rate_limit("resend", 5, 600))]
)
def resend_verification(
    request: ResendVerificationRequest, db: Session = Depends(get_db)
):
    user = (
        db.query(User)
        .filter(func.lower(User.email) == normalize_email(request.email))
        .first()
    )
    if user and not user.email_verified and is_mailtrap_configured():
        _send_verification_otp(db, user)
    # Luôn trả cùng một thông báo để không lộ email nào đã đăng ký
    return {"message": "Nếu email cần xác minh, mã OTP mới đã được gửi."}


@router.post("/refresh", dependencies=[Depends(rate_limit("refresh", 30, 60))])
def refresh_session(request: RefreshRequest, db: Session = Depends(get_db)):
    """Đổi refresh token lấy cặp token mới; token cũ bị thu hồi (xoay vòng)."""
    invalid = HTTPException(status_code=401, detail="Phiên đăng nhập đã hết hạn")
    record = (
        db.query(RefreshToken)
        .filter(RefreshToken.token_hash == hash_refresh_token(request.refresh_token))
        .first()
    )
    if record is None:
        raise invalid
    if record.revoked:
        # Token đã dùng mà còn bị đem ra dùng lại: nghi bị lộ, thu hồi cả chuỗi
        _revoke_refresh_tokens(db, record.user_id)
        db.commit()
        raise invalid
    user = db.query(User).filter(User.id == record.user_id).first()
    if record.expires_at <= utcnow() or user is None:
        raise invalid
    record.revoked = True
    return _start_session(db, user)


@router.post("/logout")
def logout(request: RefreshRequest, db: Session = Depends(get_db)):
    """Thu hồi refresh token của thiết bị này (access token tự hết hạn)."""
    db.query(RefreshToken).filter(
        RefreshToken.token_hash == hash_refresh_token(request.refresh_token)
    ).update({"revoked": True})
    db.commit()
    return {"message": "Đã đăng xuất"}


@router.post("/logout-all")
def logout_all_devices(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Thu hồi mọi token đã cấp, kể cả token của thiết bị này."""
    current_user.token_version = (current_user.token_version or 0) + 1
    _revoke_refresh_tokens(db, current_user.id)
    db.commit()
    return {"message": "Đã đăng xuất khỏi tất cả thiết bị"}


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

    now = utcnow()
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

    now = utcnow()
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
    # Đặt lại mật khẩu thì các phiên cũ phải hết hiệu lực
    user.token_version = (user.token_version or 0) + 1
    _revoke_refresh_tokens(db, user.id)
    db.delete(reset_record)
    db.commit()
    return {"message": "Đặt lại mật khẩu thành công"}