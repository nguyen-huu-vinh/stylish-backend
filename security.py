from datetime import datetime, timedelta
from jose import jwt
from passlib.context import CryptContext
from config import SECRET_KEY, ALGORITHM, ACCESS_TOKEN_EXPIRE_MINUTES

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password):
    return pwd_context.hash(password)


def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


MIN_PASSWORD_LENGTH = 8


def check_password_strength(password: str) -> None:
    """Raise HTTPException 400 nếu mật khẩu quá yếu."""
    from fastapi import HTTPException

    if len(password or "") < MIN_PASSWORD_LENGTH:
        raise HTTPException(
            status_code=400,
            detail=f"Mật khẩu phải có ít nhất {MIN_PASSWORD_LENGTH} ký tự!",
        )
    if not any(c.isalpha() for c in password) or not any(c.isdigit() for c in password):
        raise HTTPException(
            status_code=400, detail="Mật khẩu phải gồm cả chữ và số!"
        )


def normalize_email(email: str) -> str:
    return (email or "").strip().lower()
