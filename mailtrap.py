import ssl
import smtplib
from email.message import EmailMessage

from config import (
    MAILTRAP_HOST,
    MAILTRAP_PORT,
    MAILTRAP_USERNAME,
    MAILTRAP_PASSWORD,
    MAIL_FROM_EMAIL,
    MAIL_FROM_NAME,
)


def is_mailtrap_configured():
    return bool(MAILTRAP_USERNAME and MAILTRAP_PASSWORD)


def send_password_reset_otp(recipient: str, otp: str):
    if not is_mailtrap_configured():
        raise RuntimeError("Mailtrap credentials are not configured")

    message = EmailMessage()
    message["Subject"] = "Mã OTP đặt lại mật khẩu Stylish"
    message["From"] = f"{MAIL_FROM_NAME} <{MAIL_FROM_EMAIL}>"
    message["To"] = recipient
    message.set_content(
        f"Mã OTP đặt lại mật khẩu của bạn là {otp}. "
        "Mã có hiệu lực trong 10 phút. Nếu bạn không yêu cầu, hãy bỏ qua email này."
    )

    with smtplib.SMTP(MAILTRAP_HOST, MAILTRAP_PORT, timeout=10) as server:
        server.ehlo()
        server.starttls(context=ssl.create_default_context())
        server.ehlo()
        server.login(MAILTRAP_USERNAME, MAILTRAP_PASSWORD)
        server.send_message(message)