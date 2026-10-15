from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from dependencies import get_current_user, get_db
from models import Notification, User

router = APIRouter(tags=["Notifications"])

MAX_ITEMS = 50


def _unread_count(db: Session, user_id: int) -> int:
    return (
        db.query(func.count(Notification.id))
        .filter(Notification.user_id == user_id, Notification.is_read.is_(False))
        .scalar()
    )


@router.get("/me/notifications")
def list_notifications(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    rows = (
        db.query(Notification)
        .filter(Notification.user_id == current_user.id)
        .order_by(Notification.created_at.desc(), Notification.id.desc())
        .limit(MAX_ITEMS)
        .all()
    )
    return {
        "unread": _unread_count(db, current_user.id),
        "items": [
            {
                "id": n.id,
                "title": n.title,
                "body": n.body,
                "order_id": n.order_id,
                "is_read": n.is_read,
                "created_at": n.created_at.isoformat(),
            }
            for n in rows
        ],
    }


@router.get("/me/notifications/unread-count")
def unread_count(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return {"unread": _unread_count(db, current_user.id)}


@router.post("/me/notifications/read-all")
def mark_all_read(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    db.query(Notification).filter(
        Notification.user_id == current_user.id, Notification.is_read.is_(False)
    ).update({Notification.is_read: True}, synchronize_session=False)
    db.commit()
    return {"unread": 0}


@router.post("/me/notifications/{notification_id}/read")
def mark_read(
    notification_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    n = (
        db.query(Notification)
        .filter(Notification.id == notification_id, Notification.user_id == current_user.id)
        .first()
    )
    if not n:
        raise HTTPException(status_code=404, detail="Không tìm thấy thông báo")
    n.is_read = True
    db.commit()
    return {"unread": _unread_count(db, current_user.id)}
