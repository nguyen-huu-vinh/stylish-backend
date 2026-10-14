import secrets
from urllib.parse import quote, urlencode

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, selectinload

from config import BANK_ACCOUNT_NAME, BANK_ACCOUNT_NO, BANK_ID
from dependencies import get_db, get_current_admin, get_current_user
from models import Order, OrderEvent, OrderItem, Product, User
from routers.coupons import calculate_discount, release_coupon, reuse_coupon
from routers.products import product_sizes
from schemas import OrderCancel, OrderCreate, OrderStatusUpdate

router = APIRouter(tags=["Orders"])


def _sale_price(product: Product) -> float:
    if product.discount_price is not None and product.discount_price < product.price:
        return product.discount_price
    return product.price


def _locked_products(db: Session, product_ids) -> dict:
    # Khóa các dòng sản phẩm tới khi commit (PostgreSQL) để hai đơn đặt cùng
    # lúc không cùng mua được món cuối cùng; SQLite bỏ qua FOR UPDATE
    return {
        product.id: product
        for product in db.query(Product)
        .filter(Product.id.in_(set(product_ids)))
        .with_for_update()
        .all()
    }


def _take_stock(db: Session, items) -> None:
    """Trừ kho cho các dòng đơn; báo lỗi rõ ràng nếu không đủ hàng."""
    products = _locked_products(db, [item.product_id for item in items])
    needed = {}
    for item in items:
        product = products.get(item.product_id)
        if product is not None and product.stock is not None:
            needed[product.id] = needed.get(product.id, 0) + item.quantity

    for product_id, quantity in needed.items():
        product = products[product_id]
        if product.stock < quantity:
            raise HTTPException(
                status_code=400,
                detail=(
                    f'"{product.name}" đã hết hàng'
                    if product.stock <= 0
                    else f'"{product.name}" chỉ còn {product.stock} sản phẩm'
                ),
            )

    for item in items:
        product = products.get(item.product_id)
        if product is not None and product.stock is not None:
            product.stock -= item.quantity
            item.stock_deducted = True


def _return_stock(db: Session, items) -> None:
    """Hoàn kho cho các dòng đã trừ (khi đơn bị hủy)."""
    products = _locked_products(db, [item.product_id for item in items])
    for item in items:
        product = products.get(item.product_id)
        if item.stock_deducted and product is not None and product.stock is not None:
            product.stock += item.quantity
        item.stock_deducted = False


def _bank_transfer_enabled() -> bool:
    return bool(BANK_ID and BANK_ACCOUNT_NO and BANK_ACCOUNT_NAME)


def _bank_transfer(order: Order):
    if order.payment_method != "bank" or not _bank_transfer_enabled():
        return None
    content = f"DH{order.id}"
    amount = round(order.total)
    query = urlencode({
        "amount": amount,
        "addInfo": content,
        "accountName": BANK_ACCOUNT_NAME,
    })
    return {
        "bank_id": BANK_ID,
        "account_no": BANK_ACCOUNT_NO,
        "account_name": BANK_ACCOUNT_NAME,
        "amount": amount,
        "content": content,
        # Ảnh QR chuẩn VietQR, quét được bằng mọi app ngân hàng
        "qr_url": (
            f"https://img.vietqr.io/image/{quote(BANK_ID)}-{quote(BANK_ACCOUNT_NO)}"
            f"-compact2.png?{query}"
        ),
    }


def _timeline(order: Order):
    events = [
        {
            "status": event.status,
            "note": event.note,
            "created_at": event.created_at.isoformat(),
        }
        for event in order.events
    ]
    # Đơn tạo trước khi có bảng order_events: dựng lại mốc đặt hàng
    if not events or events[0]["status"] != "pending":
        events.insert(0, {
            "status": "pending",
            "note": None,
            "created_at": order.created_at.isoformat(),
        })
    return events


def _admin_order_response(order: Order):
    # Chỉ admin mới thấy mã link shipper
    return {**_order_response(order), "tracking_token": order.tracking_token}


def _order_response(order: Order):
    return {
        "id": order.id,
        "user_id": order.user_id,
        "full_name": order.full_name,
        "phone": order.phone,
        "address": order.address,
        "note": order.note,
        "payment_method": order.payment_method,
        "status": order.status,
        "total": order.total,
        "discount": order.discount or 0,
        "coupon_code": order.coupon_code,
        "created_at": order.created_at.isoformat(),
        "bank_transfer": _bank_transfer(order),
        "timeline": _timeline(order),
        "items": [
            {
                "product_id": item.product_id,
                "product_name": item.product_name,
                "image_url": item.image_url,
                "size": item.size,
                "unit_price": item.unit_price,
                "quantity": item.quantity,
            }
            for item in order.items
        ],
    }


@router.post("/orders", status_code=201)
def create_order(
    data: OrderCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if data.payment_method == "bank" and not _bank_transfer_enabled():
        raise HTTPException(
            status_code=400,
            detail="Cửa hàng chưa hỗ trợ chuyển khoản, vui lòng chọn thanh toán khi nhận hàng",
        )

    product_ids = {item.product_id for item in data.items}
    products = _locked_products(db, product_ids)
    missing = product_ids - products.keys()
    if missing:
        raise HTTPException(
            status_code=400,
            detail="Một số sản phẩm không còn tồn tại, vui lòng cập nhật giỏ hàng",
        )

    # Giá luôn lấy từ database, không tin giá do app gửi lên
    order_items = []
    for item in data.items:
        product = products[item.product_id]
        sizes = product_sizes(product)
        size = item.size.strip() if item.size else None
        if sizes and size not in sizes:
            raise HTTPException(
                status_code=400,
                detail=(
                    f'Vui lòng chọn size cho "{product.name}"'
                    if not size
                    else f'"{product.name}" không có size {size}, vui lòng chọn lại'
                ),
            )
        order_items.append(OrderItem(
            product_id=product.id,
            product_name=product.name,
            image_url=product.image_url,
            # Sản phẩm không có size (VD mỹ phẩm) thì bỏ qua size gửi lên
            size=size if sizes else None,
            unit_price=_sale_price(product),
            quantity=item.quantity,
        ))
    _take_stock(db, order_items)

    subtotal = sum(item.unit_price * item.quantity for item in order_items)
    coupon, discount = None, 0.0
    if data.coupon_code and data.coupon_code.strip():
        coupon, discount = calculate_discount(
            db, data.coupon_code, subtotal, current_user, lock=True
        )
        coupon.used_count += 1

    note = data.note.strip() if data.note else None
    order = Order(
        user_id=current_user.id,
        full_name=data.full_name.strip(),
        phone=data.phone,
        address=data.address.strip(),
        note=note or None,
        payment_method=data.payment_method,
        status="pending",
        total=subtotal - discount,
        discount=discount,
        coupon_code=coupon.code if coupon else None,
        items=order_items,
        events=[OrderEvent(status="pending")],
    )
    db.add(order)
    db.commit()
    db.refresh(order)
    return _order_response(order)


@router.get("/orders/me")
def get_my_orders(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    orders = (
        db.query(Order)
        .options(selectinload(Order.items), selectinload(Order.events))
        .filter(Order.user_id == current_user.id)
        .order_by(Order.created_at.desc())
        .all()
    )
    return [_order_response(order) for order in orders]


@router.get("/orders/{order_id}")
def get_order_detail(
    order_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    order = db.query(Order).filter(Order.id == order_id).first()
    # Trả 404 cả khi đơn của người khác để không lộ đơn tồn tại
    if not order or (order.user_id != current_user.id and not current_user.is_admin):
        raise HTTPException(status_code=404, detail="Không tìm thấy đơn hàng")
    return _order_response(order)


@router.post("/orders/{order_id}/cancel")
def cancel_my_order(
    order_id: int,
    data: OrderCancel,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order or order.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Không tìm thấy đơn hàng")
    if order.status != "pending":
        raise HTTPException(
            status_code=400,
            detail="Chỉ có thể hủy đơn khi đơn đang chờ xác nhận",
        )

    reason = data.reason.strip() if data.reason else ""
    _return_stock(db, order.items)
    release_coupon(db, order)
    order.status = "cancelled"
    order.events.append(OrderEvent(
        status="cancelled",
        note=f"Bạn đã hủy đơn: {reason}" if reason else "Bạn đã hủy đơn",
    ))
    db.commit()
    db.refresh(order)
    return _order_response(order)


@router.get("/admin/orders")
def get_all_orders(
    db: Session = Depends(get_db),
    current_admin: User = Depends(get_current_admin),
):
    orders = (
        db.query(Order)
        .options(selectinload(Order.items), selectinload(Order.events))
        .order_by(Order.created_at.desc())
        .all()
    )
    return [_admin_order_response(order) for order in orders]


@router.put("/admin/orders/{order_id}/status")
def update_order_status(
    order_id: int,
    data: OrderStatusUpdate,
    db: Session = Depends(get_db),
    current_admin: User = Depends(get_current_admin),
):
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Không tìm thấy đơn hàng")
    note = data.note.strip() if data.note else None
    # Chọn lại đúng trạng thái cũ mà không có ghi chú thì không tạo mốc mới
    if data.status == order.status and not note:
        return _admin_order_response(order)

    # Hủy thì hoàn kho; mở lại đơn đã hủy thì phải trừ kho lại (có thể hết hàng)
    if data.status == "cancelled" and order.status != "cancelled":
        _return_stock(db, order.items)
        release_coupon(db, order)
    elif order.status == "cancelled" and data.status != "cancelled":
        _take_stock(db, order.items)
        reuse_coupon(db, order)

    order.status = data.status
    order.events.append(OrderEvent(status=data.status, note=note or None))
    if data.status == "shipping" and not order.tracking_token:
        order.tracking_token = secrets.token_urlsafe(16)
    db.commit()
    db.refresh(order)
    return _admin_order_response(order)
