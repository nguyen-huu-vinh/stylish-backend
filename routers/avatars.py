import secrets
from datetime import datetime
from timeutil import utcnow

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from sqlalchemy.orm import Session

from dependencies import get_current_user, get_db
from models import User, UserAvatar
from routers.auth import avatar_url

router = APIRouter(tags=["Avatars"])

# App đã thu nhỏ ảnh còn 512px (~50 KB) nên 2 MB là dư dả
MAX_AVATAR_BYTES = 2 * 1024 * 1024


def _image_type(data: bytes):
    """Nhận dạng ảnh theo vài byte đầu, không tin đuôi file hay content-type."""
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


@router.post("/me/avatar")
async def upload_avatar(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    data = await file.read(MAX_AVATAR_BYTES + 1)
    if len(data) > MAX_AVATAR_BYTES:
        raise HTTPException(status_code=413, detail="Ảnh quá lớn, tối đa 2 MB")
    content_type = _image_type(data)
    if content_type is None:
        raise HTTPException(status_code=400, detail="Chỉ hỗ trợ ảnh JPG, PNG hoặc WEBP")

    avatar = current_user.avatar or UserAvatar(user_id=current_user.id)
    avatar.key = secrets.token_urlsafe(16)
    avatar.content_type = content_type
    avatar.data = data
    avatar.updated_at = utcnow()
    current_user.avatar = avatar
    db.commit()
    db.refresh(current_user)
    return {"avatar_url": avatar_url(current_user)}


@router.delete("/me/avatar")
def delete_avatar(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    current_user.avatar = None
    db.commit()
    return {"avatar_url": None}


@router.get("/avatars/{key}")
def get_avatar(key: str, db: Session = Depends(get_db)):
    avatar = db.query(UserAvatar).filter(UserAvatar.key == key).first()
    if not avatar:
        raise HTTPException(status_code=404, detail="Không tìm thấy ảnh")
    # Mỗi ảnh có mã riêng, đổi ảnh là đổi mã, nên cho phép lưu cache lâu dài
    return Response(
        content=avatar.data,
        media_type=avatar.content_type,
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )
