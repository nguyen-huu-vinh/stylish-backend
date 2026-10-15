"""Gửi push notification qua Firebase Cloud Messaging (HTTP v1).

Không dùng thư viện firebase-admin (nặng) mà tự làm 2 bước:
  1. Ký một JWT bằng khóa private của service account, đổi lấy access token OAuth2.
  2. Gọi API https://fcm.googleapis.com/v1/projects/<id>/messages:send cho từng token.
Chưa cấu hình FIREBASE_SERVICE_ACCOUNT_JSON thì mọi hàm gửi chỉ bỏ qua, không lỗi.
"""
import json
import logging
import time
from typing import Optional

import requests
from jose import jwt

from config import FIREBASE_SERVICE_ACCOUNT_JSON
from database import SessionLocal
from models import DeviceToken, Notification

logger = logging.getLogger(__name__)

_SCOPE = "https://www.googleapis.com/auth/firebase.messaging"
_account = None
_access_token = None
_access_token_expires = 0.0


def push_enabled() -> bool:
    return _load_account() is not None


def _load_account():
    global _account
    if _account is None and FIREBASE_SERVICE_ACCOUNT_JSON:
        try:
            _account = json.loads(FIREBASE_SERVICE_ACCOUNT_JSON)
        except ValueError:
            logger.error("FIREBASE_SERVICE_ACCOUNT_JSON không phải JSON hợp lệ")
            _account = {}
    return _account or None


def _get_access_token(account) -> str:
    # Access token sống 1 giờ nên giữ lại dùng chung, tránh xin mới mỗi lần gửi
    global _access_token, _access_token_expires
    if _access_token and time.time() < _access_token_expires - 60:
        return _access_token

    now = int(time.time())
    assertion = jwt.encode(
        {
            "iss": account["client_email"],
            "scope": _SCOPE,
            "aud": "https://oauth2.googleapis.com/token",
            "iat": now,
            "exp": now + 3600,
        },
        account["private_key"],
        algorithm="RS256",
    )
    res = requests.post(
        "https://oauth2.googleapis.com/token",
        data={
            "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
            "assertion": assertion,
        },
        timeout=10,
    )
    res.raise_for_status()
    data = res.json()
    _access_token = data["access_token"]
    _access_token_expires = time.time() + int(data.get("expires_in", 3600))
    return _access_token


def send_push(user_id: int, title: str, body: str, data: Optional[dict] = None) -> None:
    """Gửi thông báo tới mọi thiết bị của user. Chạy nền, tự mở session riêng."""
    account = _load_account()
    if not account:
        return

    db = SessionLocal()
    try:
        tokens = [
            row.token
            for row in db.query(DeviceToken).filter(DeviceToken.user_id == user_id)
        ]
        if not tokens:
            return
        try:
            access_token = _get_access_token(account)
        except Exception:
            logger.exception("Không lấy được access token FCM")
            return

        url = (
            "https://fcm.googleapis.com/v1/projects/"
            f"{account['project_id']}/messages:send"
        )
        dead = []
        for token in tokens:
            message = {
                "token": token,
                "notification": {"title": title, "body": body},
                # FCM chỉ nhận giá trị chuỗi trong data
                "data": {k: str(v) for k, v in (data or {}).items()},
                "android": {"priority": "HIGH"},
            }
            try:
                res = requests.post(
                    url,
                    json={"message": message},
                    headers={"Authorization": f"Bearer {access_token}"},
                    timeout=10,
                )
            except requests.RequestException:
                logger.exception("Gửi FCM thất bại")
                continue
            # Token đã gỡ app hoặc hết hạn: xóa để lần sau khỏi gửi vô ích
            if res.status_code == 404 or "UNREGISTERED" in res.text:
                dead.append(token)
            elif res.status_code >= 400:
                logger.warning("FCM trả %s: %s", res.status_code, res.text)

        if dead:
            db.query(DeviceToken).filter(DeviceToken.token.in_(dead)).delete(
                synchronize_session=False
            )
            db.commit()
    finally:
        db.close()


ORDER_MESSAGES = {
    "pending": ("Đặt hàng thành công", "Đơn #{id} đang chờ shop xác nhận."),
    "confirmed": ("Đơn hàng đã được xác nhận", "Đơn #{id} đang được shop chuẩn bị."),
    "shipping": ("Đơn hàng đang được giao", "Đơn #{id} đã giao cho shipper, mở app để theo dõi trên bản đồ."),
    "completed": ("Giao hàng thành công", "Đơn #{id} đã được giao. Bạn hãy đánh giá sản phẩm nhé!"),
    "cancelled": ("Đơn hàng đã bị hủy", "Đơn #{id} đã bị hủy."),
}


def record_order_notification(db, order_id: int, user_id: int, status: str) -> None:
    """Lưu thông báo vào hộp thư (chưa commit, đi cùng giao dịch của đơn)."""
    message = ORDER_MESSAGES.get(status)
    if not message:
        return
    title, body = message
    db.add(Notification(
        user_id=user_id, title=title, body=body.format(id=order_id),
        order_id=order_id,
    ))


def notify_order_status(order_id: int, user_id: int, status: str) -> None:
    message = ORDER_MESSAGES.get(status)
    if not message:
        return
    title, body = message
    send_push(
        user_id,
        title,
        body.format(id=order_id),
        {"type": "order", "order_id": order_id, "status": status},
    )
