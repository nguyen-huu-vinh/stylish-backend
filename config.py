import os
from dotenv import load_dotenv

load_dotenv()

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

MAILTRAP_HOST = os.getenv("MAILTRAP_HOST", "sandbox.smtp.mailtrap.io")
MAILTRAP_PORT = int(os.getenv("MAILTRAP_PORT", "2525"))
MAILTRAP_USERNAME = os.getenv("MAILTRAP_USERNAME")
MAILTRAP_PASSWORD = os.getenv("MAILTRAP_PASSWORD")
MAIL_FROM_EMAIL = os.getenv("MAIL_FROM_EMAIL", "no-reply@stylish.local")
MAIL_FROM_NAME = os.getenv("MAIL_FROM_NAME", "Stylish")

# Tài khoản nhận chuyển khoản (VietQR). BANK_ID là mã BIN hoặc tên viết tắt
# ngân hàng theo vietqr.io, ví dụ: 970436 hoặc VCB, MB, TCB, ACB...
BANK_ID = os.getenv("BANK_ID")
BANK_ACCOUNT_NO = os.getenv("BANK_ACCOUNT_NO")
BANK_ACCOUNT_NAME = os.getenv("BANK_ACCOUNT_NAME")
