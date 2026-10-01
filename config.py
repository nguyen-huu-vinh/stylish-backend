import os

SECRET_KEY = os.getenv("SECRET_KEY")
if not SECRET_KEY:
    raise RuntimeError(
        "Thiếu biến môi trường SECRET_KEY. Hãy đặt SECRET_KEY trước khi chạy server "
        "(ví dụ: export SECRET_KEY=$(openssl rand -hex 32))."
    )

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24  # 1 ngày

ADMIN_EMAIL = os.getenv("ADMIN_EMAIL")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD")