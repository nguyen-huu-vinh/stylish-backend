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
ACCESS_TOKEN_EXPIRE_MINUTES = int(
    os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", str(60 * 24))  # mặc định 1 ngày
)
REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "30"))

# Bật thì tài khoản mới phải xác minh email (OTP) mới đăng nhập được. Mặc định
# tắt để app bản cũ không bị khóa; chỉ có tác dụng khi đã cấu hình Mailtrap.
REQUIRE_EMAIL_VERIFICATION = os.getenv("REQUIRE_EMAIL_VERIFICATION", "").lower() in (
    "1", "true", "yes",
)

# Số ngày kể từ lúc giao xong mà khách còn được yêu cầu trả hàng
RETURN_WINDOW_DAYS = int(os.getenv("RETURN_WINDOW_DAYS", "7"))

ADMIN_EMAIL = os.getenv("ADMIN_EMAIL")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD")

MAILTRAP_HOST = os.getenv("MAILTRAP_HOST", "sandbox.smtp.mailtrap.io")
MAILTRAP_PORT = int(os.getenv("MAILTRAP_PORT", "2525"))
MAILTRAP_USERNAME = os.getenv("MAILTRAP_USERNAME")
MAILTRAP_PASSWORD = os.getenv("MAILTRAP_PASSWORD")
MAIL_FROM_EMAIL = os.getenv("MAIL_FROM_EMAIL", "no-reply@stylish.local")
MAIL_FROM_NAME = os.getenv("MAIL_FROM_NAME", "Stylish")

# Vị trí cửa hàng hiện trên bản đồ theo dõi đơn (bỏ trống thì không hiện)
SHOP_NAME = os.getenv("SHOP_NAME", "Stylish")
SHOP_LAT = float(os.getenv("SHOP_LAT")) if os.getenv("SHOP_LAT") else None
SHOP_LNG = float(os.getenv("SHOP_LNG")) if os.getenv("SHOP_LNG") else None

# Tài khoản nhận chuyển khoản (VietQR). BANK_ID là mã BIN hoặc tên viết tắt
# ngân hàng theo vietqr.io, ví dụ: 970436 hoặc VCB, MB, TCB, ACB...
BANK_ID = os.getenv("BANK_ID")
BANK_ACCOUNT_NO = os.getenv("BANK_ACCOUNT_NO")
BANK_ACCOUNT_NAME = os.getenv("BANK_ACCOUNT_NAME")

# Các OAuth client ID của Google được phép đăng nhập (web/server, iOS, Android),
# cách nhau dấu phẩy. Bỏ trống thì tắt đăng nhập Google.
GOOGLE_CLIENT_IDS = [
    cid.strip()
    for cid in os.getenv("GOOGLE_CLIENT_IDS", "").split(",")
    if cid.strip()
]

# Nội dung file JSON service account của Firebase (Project settings > Service
# accounts > Generate new private key). Bỏ trống thì tắt tính năng push.
FIREBASE_SERVICE_ACCOUNT_JSON = os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON")
