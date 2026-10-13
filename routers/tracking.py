import os
import secrets
from datetime import datetime

import requests
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from sqlalchemy.orm import Session

from config import SHOP_LAT, SHOP_LNG, SHOP_NAME
from dependencies import get_current_user, get_db
from models import Order, OrderEvent, User
from schemas import ShipperLocation, ShipperToken

router = APIRouter(tags=["Order tracking"])

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
# Nominatim yêu cầu User-Agent riêng cho từng ứng dụng
NOMINATIM_HEADERS = {"User-Agent": "StylishShop/1.0 (order tracking)"}


def _geocode(address: str):
    """Đổi địa chỉ ra (lat, lng) bằng OpenStreetMap Nominatim.

    Địa chỉ Việt Nam có số nhà, hẻm thường không tìm thấy nguyên văn, nên
    bỏ dần phần đầu (số nhà, đường...) cho tới khi ra kết quả ở mức phường,
    quận. Trả về None nếu không tìm được; lỗi mạng thì ném lỗi để thử lại sau.
    """
    parts = [part.strip() for part in address.split(",") if part.strip()]
    candidates = [", ".join(parts[i:]) for i in range(len(parts))] or [address]
    for query in candidates[:4]:
        res = requests.get(
            NOMINATIM_URL,
            params={"q": query, "format": "json", "limit": 1, "countrycodes": "vn"},
            headers=NOMINATIM_HEADERS,
            timeout=6,
        )
        res.raise_for_status()
        results = res.json()
        if results:
            return float(results[0]["lat"]), float(results[0]["lon"])
    return None


def _ensure_destination(order: Order, db: Session):
    if order.geocoded:
        return
    try:
        coords = _geocode(order.address)
    except requests.RequestException:
        return  # mạng lỗi: lần mở sau thử lại
    if coords:
        order.delivery_lat, order.delivery_lng = coords
    # Không tìm thấy cũng đánh dấu để không gọi Nominatim mỗi lần app hỏi
    order.geocoded = True
    db.commit()


def _point(lat, lng, **extra):
    if lat is None or lng is None:
        return None
    return {"lat": lat, "lng": lng, **extra}


@router.get("/orders/{order_id}/tracking")
def get_order_tracking(
    order_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order or (order.user_id != current_user.id and not current_user.is_admin):
        raise HTTPException(status_code=404, detail="Không tìm thấy đơn hàng")

    _ensure_destination(order, db)
    # Chỉ lộ vị trí shipper khi đơn đang giao
    shipper = None
    if order.status == "shipping" and order.shipper_updated_at:
        shipper = _point(
            order.shipper_lat,
            order.shipper_lng,
            updated_at=order.shipper_updated_at.isoformat(),
        )
    return {
        "order_id": order.id,
        "status": order.status,
        "shop": _point(SHOP_LAT, SHOP_LNG, name=SHOP_NAME),
        "destination": _point(
            order.delivery_lat, order.delivery_lng, address=order.address
        ),
        "shipper": shipper,
    }


# --- Trang và API cho shipper: xác thực bằng mã bí mật trong link ---

def _shipper_order(order_id: int, token: str, db: Session) -> Order:
    order = db.query(Order).filter(Order.id == order_id).first()
    if (
        not order
        or not order.tracking_token
        or not secrets.compare_digest(order.tracking_token, token)
    ):
        raise HTTPException(status_code=404, detail="Link giao hàng không hợp lệ")
    return order


@router.get("/shipper", response_class=HTMLResponse)
def get_shipper_page():
    if os.path.exists("shipper.html"):
        return FileResponse("shipper.html")
    return "<h1>Chưa tìm thấy file shipper.html!</h1>"


@router.get("/shipper/orders/{order_id}")
def get_shipper_order(order_id: int, token: str, db: Session = Depends(get_db)):
    order = _shipper_order(order_id, token, db)
    return {
        "id": order.id,
        "code": f"DH{order.id}",
        "status": order.status,
        "full_name": order.full_name,
        "phone": order.phone,
        "address": order.address,
        "note": order.note,
        "payment_method": order.payment_method,
        "total": order.total,
    }


@router.post("/shipper/orders/{order_id}/location")
def update_shipper_location(
    order_id: int, data: ShipperLocation, db: Session = Depends(get_db)
):
    order = _shipper_order(order_id, data.token, db)
    if order.status != "shipping":
        raise HTTPException(status_code=400, detail="Đơn không còn ở trạng thái đang giao")
    order.shipper_lat = data.lat
    order.shipper_lng = data.lng
    order.shipper_updated_at = datetime.utcnow()
    db.commit()
    return {"ok": True}


@router.post("/shipper/orders/{order_id}/delivered")
def mark_delivered(order_id: int, data: ShipperToken, db: Session = Depends(get_db)):
    order = _shipper_order(order_id, data.token, db)
    if order.status != "shipping":
        raise HTTPException(status_code=400, detail="Đơn không còn ở trạng thái đang giao")
    order.status = "completed"
    order.events.append(OrderEvent(
        status="completed", note="Shipper đã giao hàng thành công",
    ))
    db.commit()
    return {"ok": True}
