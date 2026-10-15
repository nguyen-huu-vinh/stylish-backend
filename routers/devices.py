from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from dependencies import get_db, get_current_user
from models import DeviceToken, User
from schemas import DeviceTokenIn

router = APIRouter(tags=["Devices"])


@router.post("/me/devices")
def register_device(
    data: DeviceTokenIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """App gọi sau khi đăng nhập hoặc khi FCM đổi token."""
    device = db.query(DeviceToken).filter(DeviceToken.token == data.token).first()
    if device:
        # Cùng một máy đăng nhập tài khoản khác: chuyển token sang chủ mới
        device.user_id = current_user.id
        device.platform = data.platform
        device.updated_at = datetime.utcnow()
    else:
        db.add(DeviceToken(
            user_id=current_user.id, token=data.token, platform=data.platform
        ))
    db.commit()
    return {"ok": True}


@router.post("/me/devices/unregister")
def unregister_device(
    data: DeviceTokenIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """App gọi trước khi đăng xuất để máy này không nhận thông báo của tài khoản cũ."""
    db.query(DeviceToken).filter(
        DeviceToken.token == data.token, DeviceToken.user_id == current_user.id
    ).delete()
    db.commit()
    return {"ok": True}
