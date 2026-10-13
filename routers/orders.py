from urllib.parse import quote, urlencode

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, selectinload

from config import BANK_ACCOUNT_NAME, BANK_ACCOUNT_NO, BANK_ID
from dependencies import get_db, get_current_admin, get_current_user
from models import Order, OrderItem, Product, User
from schemas import OrderCreate, OrderStatusUpdate

router = APIRouter(tags=["Orders"])


def _sale_price(product: Product) -> float:
    if product.discount_price is not None and product.discount_price < product.price:
        return product.discount_price
    return product.price


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
        "created_at": order.created_at.isoformat(),
        "bank_transfer": _bank_transfer(order),
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
    products = {
        product.id: product
        for product in db.query(Product).filter(Product.id.in_(product_ids)).all()
    }
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
        order_items.append(OrderItem(
            product_id=product.id,
            product_name=product.name,
            image_url=product.image_url,
            size=item.size.strip() if item.size else None,
            unit_price=_sale_price(product),
            quantity=item.quantity,
        ))

    note = data.note.strip() if data.note else None
    order = Order(
        user_id=current_user.id,
        full_name=data.full_name.strip(),
        phone=data.phone,
        address=data.address.strip(),
        note=note or None,
        payment_method=data.payment_method,
        status="pending",
        total=sum(item.unit_price * item.quantity for item in order_items),
        items=order_items,
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
        .options(selectinload(Order.items))
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


@router.get("/admin/orders")
def get_all_orders(
    db: Session = Depends(get_db),
    current_admin: User = Depends(get_current_admin),
):
    orders = (
        db.query(Order)
        .options(selectinload(Order.items))
        .order_by(Order.created_at.desc())
        .all()
    )
    return [_order_response(order) for order in orders]


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
    order.status = data.status
    db.commit()
    db.refresh(order)
    return _order_response(order)
