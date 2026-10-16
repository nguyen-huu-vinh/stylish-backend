from datetime import timedelta
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy.orm import Session, selectinload

from config import RETURN_WINDOW_DAYS
from dependencies import get_current_admin, get_current_user, get_db
from models import Notification, Order, ReturnRequest, User
from push import send_push
from routers.orders import (
    _admin_order_response,
    _order_response,
    _return_response,
    _return_stock,
)
from schemas import RefundCreate, ReturnCreate, ReturnUpdate
from timeutil import utcnow

router = APIRouter(tags=["Returns"])

# Các bước hợp lệ của yêu cầu trả hàng; "refunded" đặt qua API hoàn tiền
_NEXT = {
    "requested": ("approved", "rejected"),
    "approved": ("received",),
}

_MESSAGES = {
    "requested": ("Đã nhận yêu cầu trả hàng", "Yêu cầu trả hàng đơn DH{id} đang chờ cửa hàng duyệt."),
    "approved": ("Yêu cầu trả hàng được chấp nhận", "Đơn DH{id}: vui lòng gửi hàng về cửa hàng."),
    "rejected": ("Yêu cầu trả hàng bị từ chối", "Cửa hàng đã từ chối yêu cầu trả hàng đơn DH{id}."),
    "received": ("Đã nhận hàng trả", "Cửa hàng đã nhận hàng trả của đơn DH{id}, sẽ hoàn tiền sớm."),
    "refunded": ("Đã hoàn tiền", "Đơn DH{id} đã được hoàn tiền."),
}


def _notify(db: Session, background_tasks: BackgroundTasks, order: Order, kind: str):
    title, body = _MESSAGES[kind]
    body = body.format(id=order.id)
    db.add(Notification(
        user_id=order.user_id, title=title, body=body, order_id=order.id,
    ))
    background_tasks.add_task(
        send_push, order.user_id, title, body,
        {"type": "order", "order_id": order.id},
    )


def _completed_at(order: Order):
    done = [e.created_at for e in order.events if e.status == "completed"]
    return max(done) if done else order.created_at


def _load_order(db: Session, order_id: int) -> Optional[Order]:
    return (
        db.query(Order)
        .options(selectinload(Order.items), selectinload(Order.events))
        .filter(Order.id == order_id)
        .first()
    )


@router.post("/orders/{order_id}/return", status_code=201)
def request_return(
    order_id: int,
    data: ReturnCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    order = _load_order(db, order_id)
    if not order or order.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Không tìm thấy đơn hàng")
    if order.status != "completed":
        raise HTTPException(
            status_code=400, detail="Chỉ đơn đã giao thành công mới trả hàng được"
        )
    if order.return_request is not None:
        raise HTTPException(status_code=400, detail="Đơn này đã có yêu cầu trả hàng")
    if utcnow() > _completed_at(order) + timedelta(days=RETURN_WINDOW_DAYS):
        raise HTTPException(
            status_code=400,
            detail=f"Đã quá {RETURN_WINDOW_DAYS} ngày kể từ khi nhận hàng",
        )
    order.return_request = ReturnRequest(
        user_id=current_user.id, reason=data.reason.strip()
    )
    _notify(db, background_tasks, order, "requested")
    db.commit()
    db.refresh(order)
    return _order_response(order)


@router.get("/admin/returns")
def list_returns(
    status: Optional[str] = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_admin: User = Depends(get_current_admin),
):
    query = db.query(ReturnRequest)
    if status:
        query = query.filter(ReturnRequest.status == status)
    requests = (
        query.order_by(ReturnRequest.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return [
        {**_return_response(r), "order": _admin_order_response(r.order)}
        for r in requests
    ]


@router.put("/admin/returns/{return_id}")
def update_return(
    return_id: int,
    data: ReturnUpdate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_admin: User = Depends(get_current_admin),
):
    request = db.query(ReturnRequest).filter(ReturnRequest.id == return_id).first()
    if not request:
        raise HTTPException(status_code=404, detail="Không tìm thấy yêu cầu trả hàng")
    if data.status not in _NEXT.get(request.status, ()):
        raise HTTPException(
            status_code=400,
            detail=f"Không thể chuyển từ '{request.status}' sang '{data.status}'",
        )
    order = _load_order(db, request.order_id)
    if data.status == "received":
        # Hàng về kho thì cộng lại tồn kho
        _return_stock(db, order.items)
    request.status = data.status
    request.admin_note = data.note.strip() if data.note else request.admin_note
    request.updated_at = utcnow()
    _notify(db, background_tasks, order, data.status)
    db.commit()
    db.refresh(order)
    return _admin_order_response(order)


@router.post("/admin/orders/{order_id}/refund")
def refund_order(
    order_id: int,
    data: RefundCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_admin: User = Depends(get_current_admin),
):
    """Ghi nhận đã hoàn tiền cho khách (việc chuyển tiền thật làm ngoài hệ thống)."""
    order = _load_order(db, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Không tìm thấy đơn hàng")
    if order.refunded_at is not None:
        raise HTTPException(status_code=400, detail="Đơn này đã được hoàn tiền")
    if not order.paid:
        raise HTTPException(status_code=400, detail="Đơn chưa thu tiền nên không có gì để hoàn")
    request = order.return_request
    eligible = order.status == "cancelled" or (
        request is not None and request.status in ("approved", "received")
    )
    if not eligible:
        raise HTTPException(
            status_code=400,
            detail="Chỉ hoàn tiền cho đơn đã hủy hoặc đơn có yêu cầu trả hàng được duyệt",
        )
    amount = data.amount if data.amount is not None else order.total
    if amount > order.total:
        raise HTTPException(status_code=400, detail="Số tiền hoàn vượt quá giá trị đơn")
    order.refund_amount = amount
    order.refunded_at = utcnow()
    if request is not None:
        request.status = "refunded"
        request.updated_at = order.refunded_at
        if data.note:
            request.admin_note = data.note.strip()
    _notify(db, background_tasks, order, "refunded")
    db.commit()
    db.refresh(order)
    return _admin_order_response(order)
