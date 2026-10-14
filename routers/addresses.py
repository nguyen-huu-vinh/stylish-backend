from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from dependencies import get_current_user, get_db
from models import Address, User
from schemas import AddressCreate

router = APIRouter(prefix="/addresses", tags=["Addresses"])

MAX_ADDRESSES = 10


def _response(address: Address):
    return {
        "id": address.id,
        "label": address.label,
        "full_name": address.full_name,
        "phone": address.phone,
        "address": address.address,
        "lat": address.lat,
        "lng": address.lng,
        "is_default": address.is_default,
    }


def _mine(db: Session, user: User):
    return db.query(Address).filter(Address.user_id == user.id)


def _get_mine(db: Session, user: User, address_id: int) -> Address:
    address = _mine(db, user).filter(Address.id == address_id).first()
    if not address:
        raise HTTPException(status_code=404, detail="Không tìm thấy địa chỉ")
    return address


def _apply(address: Address, data: AddressCreate):
    address.label = data.label.strip() if data.label else None
    address.full_name = data.full_name.strip()
    address.phone = data.phone
    address.address = data.address.strip()
    address.lat = data.lat
    address.lng = data.lng


@router.get("")
def list_addresses(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    addresses = (
        _mine(db, current_user)
        .order_by(Address.is_default.desc(), Address.id.desc())
        .all()
    )
    return [_response(address) for address in addresses]


@router.post("", status_code=201)
def create_address(
    data: AddressCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    existing = _mine(db, current_user).count()
    if existing >= MAX_ADDRESSES:
        raise HTTPException(
            status_code=400, detail=f"Chỉ lưu tối đa {MAX_ADDRESSES} địa chỉ"
        )
    address = Address(user_id=current_user.id)
    _apply(address, data)
    # Địa chỉ đầu tiên luôn là mặc định
    address.is_default = data.is_default or existing == 0
    if address.is_default:
        _mine(db, current_user).update({Address.is_default: False})
    db.add(address)
    db.commit()
    db.refresh(address)
    return _response(address)


@router.put("/{address_id}")
def update_address(
    address_id: int,
    data: AddressCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    address = _get_mine(db, current_user, address_id)
    _apply(address, data)
    if data.is_default and not address.is_default:
        _mine(db, current_user).update({Address.is_default: False})
        address.is_default = True
    db.commit()
    db.refresh(address)
    return _response(address)


@router.post("/{address_id}/default")
def set_default_address(
    address_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    address = _get_mine(db, current_user, address_id)
    _mine(db, current_user).update({Address.is_default: False})
    address.is_default = True
    db.commit()
    db.refresh(address)
    return _response(address)


@router.delete("/{address_id}")
def delete_address(
    address_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    address = _get_mine(db, current_user, address_id)
    was_default = address.is_default
    db.delete(address)
    db.flush()
    # Xóa địa chỉ mặc định thì chuyển mặc định cho địa chỉ mới nhất còn lại
    if was_default:
        newest = _mine(db, current_user).order_by(Address.id.desc()).first()
        if newest:
            newest.is_default = True
    db.commit()
    return {"message": "Đã xóa địa chỉ"}
