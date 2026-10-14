from datetime import datetime, timezone
from typing import Literal, Optional
from pydantic import BaseModel, EmailStr, Field, model_validator


class UserRegister(BaseModel):
    email: str
    password: str
    full_name: Optional[str] = None


class PasswordChange(BaseModel):
    current_password: str
    new_password: str


class ForgotPasswordRequest(BaseModel):
    email: str


class ResetPasswordRequest(BaseModel):
    email: str
    otp: str = Field(pattern=r"^\d{6}$")
    new_password: str


class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    email: Optional[str] = None
    is_admin: Optional[bool] = None
    password: Optional[str] = None


class UserProfileUpdate(BaseModel):
    full_name: Optional[str] = Field(default=None, max_length=120)
    email: Optional[EmailStr] = Field(default=None, max_length=254)


class CategoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class CategoryUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class ProductSchema(BaseModel):
    name: str
    price: float
    category_id: int
    description: Optional[str] = None
    discount_price: Optional[float] = None
    image_url: str
    is_sale: bool = False
    is_deal_of_the_day: bool = False
    is_trending: bool = False
    is_new: bool = False
    # None = không giới hạn số lượng
    stock: Optional[int] = Field(default=None, ge=0, le=1_000_000)
    # None = dùng size mặc định; [] = sản phẩm không có size
    sizes: Optional[list[str]] = Field(default=None, max_length=20)

    @model_validator(mode="after")
    def clean_sizes(self):
        if self.sizes is not None:
            cleaned = []
            for size in self.sizes:
                size = size.strip()
                if "," in size or len(size) > 20:
                    raise ValueError("Size không hợp lệ")
                if size and size not in cleaned:
                    cleaned.append(size)
            self.sizes = cleaned
        return self

    @model_validator(mode="after")
    def validate_deal_of_the_day(self):
        has_reduced_price = (
            self.discount_price is not None
            and self.discount_price < self.price
        )
        if self.is_deal_of_the_day and not (self.is_sale or has_reduced_price):
            raise ValueError(
                "Deal of the Day cần bật Sale hoặc có giá giảm thấp hơn giá gốc"
            )
        return self

    class Config:
        model_config = {"from_attributes": True}

class OrderItemCreate(BaseModel):
    product_id: int
    size: Optional[str] = Field(default=None, max_length=20)
    quantity: int = Field(ge=1, le=99)


class OrderCreate(BaseModel):
    full_name: str = Field(min_length=1, max_length=120)
    phone: str = Field(pattern=r"^\d{9,11}$")
    address: str = Field(min_length=1, max_length=500)
    note: Optional[str] = Field(default=None, max_length=500)
    payment_method: Literal["cod", "bank"]
    items: list[OrderItemCreate] = Field(min_length=1, max_length=50)
    coupon_code: Optional[str] = Field(default=None, max_length=40)


class OrderStatusUpdate(BaseModel):
    status: Literal["pending", "confirmed", "shipping", "completed", "cancelled"]
    note: Optional[str] = Field(default=None, max_length=300)


class ShipperToken(BaseModel):
    token: str = Field(min_length=10, max_length=100)


class ShipperLocation(ShipperToken):
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)


class OrderCancel(BaseModel):
    reason: Optional[str] = Field(default=None, max_length=300)


class ReviewCreate(BaseModel):
    rating: int = Field(ge=1, le=5)
    comment: Optional[str] = Field(default=None, max_length=1000)


class AddressCreate(BaseModel):
    label: Optional[str] = Field(default=None, max_length=40)
    full_name: str = Field(min_length=1, max_length=120)
    phone: str = Field(pattern=r"^\d{9,11}$")
    address: str = Field(min_length=1, max_length=500)
    lat: Optional[float] = Field(default=None, ge=-90, le=90)
    lng: Optional[float] = Field(default=None, ge=-180, le=180)
    is_default: bool = False


class CouponCreate(BaseModel):
    code: str = Field(pattern=r"^[A-Za-z0-9_-]{3,40}$")
    description: Optional[str] = Field(default=None, max_length=200)
    discount_type: Literal["percent", "fixed"]
    value: float = Field(gt=0)
    min_order: float = Field(default=0, ge=0)
    max_discount: Optional[float] = Field(default=None, gt=0)
    usage_limit: Optional[int] = Field(default=None, ge=1)
    expires_at: Optional[datetime] = None
    is_active: bool = True

    @model_validator(mode="after")
    def check_value(self):
        # Database lưu giờ UTC không kèm múi giờ
        if self.expires_at is not None and self.expires_at.tzinfo is not None:
            self.expires_at = self.expires_at.astimezone(timezone.utc).replace(
                tzinfo=None
            )
        if self.discount_type == "percent" and self.value > 100:
            raise ValueError("Giảm theo % không được vượt quá 100")
        return self


class CouponValidate(BaseModel):
    code: str = Field(min_length=1, max_length=40)
    subtotal: float = Field(ge=0)
