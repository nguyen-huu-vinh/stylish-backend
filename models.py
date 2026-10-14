from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
)
from sqlalchemy.orm import deferred, relationship
from database import Base


class CategoryDB(Base):
    __tablename__ = "categories"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, nullable=False, index=True)
    products = relationship("ProductDB", back_populates="category_ref")


class ProductDB(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    price = Column(Float, nullable=False)
    discount_price = Column(Float, nullable=True)
    description = Column(String, nullable=True)
    is_sale = Column(Boolean, default=False)
    is_deal_of_the_day = Column(Boolean, default=False)
    is_new = Column(Boolean, default=False)
    image_url = Column(String, nullable=False)
    is_trending = Column(Boolean, default=False)
    category_id = Column(Integer, ForeignKey("categories.id"), nullable=True)
    category_ref = relationship("CategoryDB", back_populates="products")
    # Số lượng còn trong kho; NULL = không giới hạn (sản phẩm cũ chưa nhập kho)
    stock = Column(Integer, nullable=True)
    # Các size cách nhau dấu phẩy, VD "S,M,L". NULL = chưa cấu hình (dùng size
    # mặc định), chuỗi rỗng = sản phẩm không có size (VD mỹ phẩm)
    sizes = Column(String, nullable=True)


class UserDB(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    full_name = Column(String, nullable=True)
    is_admin = Column(Boolean, default=False)
    avatar = relationship(
        "UserAvatarDB", uselist=False, cascade="all, delete-orphan"
    )


class UserAvatarDB(Base):
    """Ảnh đại diện lưu trong database: ổ đĩa Render bị xóa mỗi lần deploy."""

    __tablename__ = "user_avatars"

    user_id = Column(Integer, ForeignKey("users.id"), primary_key=True)
    # Mã ngẫu nhiên làm đường dẫn ảnh: không đoán được, đổi ảnh là đổi mã
    key = Column(String, unique=True, index=True, nullable=False)
    content_type = Column(String, nullable=False)
    # Chỉ tải dữ liệu ảnh khi thật sự cần (khi phục vụ ảnh), không phải mỗi /me
    data = deferred(Column(LargeBinary, nullable=False))
    updated_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class PasswordResetOTPDB(Base):
    __tablename__ = "password_reset_otps"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), unique=True, nullable=False)
    otp_hash = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    attempts = Column(Integer, default=0, nullable=False)


class OrderDB(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    full_name = Column(String, nullable=False)
    phone = Column(String, nullable=False)
    address = Column(String, nullable=False)
    note = Column(String, nullable=True)
    payment_method = Column(String, nullable=False)
    status = Column(String, default="pending", nullable=False)
    total = Column(Float, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Theo dõi đơn trên bản đồ
    delivery_lat = Column(Float, nullable=True)  # tọa độ địa chỉ nhận hàng
    delivery_lng = Column(Float, nullable=True)
    geocoded = Column(Boolean, default=False)  # đã thử đổi địa chỉ ra tọa độ
    shipper_lat = Column(Float, nullable=True)  # vị trí mới nhất của shipper
    shipper_lng = Column(Float, nullable=True)
    shipper_updated_at = Column(DateTime, nullable=True)
    # Mã bí mật trong link gửi cho shipper, tạo khi đơn chuyển sang "shipping"
    tracking_token = Column(String, nullable=True)

    items = relationship(
        "OrderItemDB", back_populates="order", cascade="all, delete-orphan"
    )
    events = relationship(
        "OrderEventDB",
        back_populates="order",
        cascade="all, delete-orphan",
        order_by="OrderEventDB.id",
    )


class OrderItemDB(Base):
    __tablename__ = "order_items"

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False, index=True)
    # Không ràng buộc khóa ngoại cứng: sản phẩm bị xóa thì đơn cũ vẫn còn
    product_id = Column(Integer, nullable=False)
    # Lưu lại tên, ảnh, giá tại thời điểm mua để đơn không đổi khi sửa sản phẩm
    product_name = Column(String, nullable=False)
    image_url = Column(String, nullable=False)
    size = Column(String, nullable=True)
    unit_price = Column(Float, nullable=False)
    quantity = Column(Integer, nullable=False)
    # Dòng này đã trừ kho chưa: chỉ hoàn kho khi hủy nếu trước đó đã trừ
    stock_deducted = Column(Boolean, default=False, nullable=False)
    order = relationship("OrderDB", back_populates="items")


class OrderEventDB(Base):
    """Một mốc trong hành trình đơn hàng, dùng cho màn hình theo dõi đơn."""

    __tablename__ = "order_events"

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False, index=True)
    status = Column(String, nullable=False)
    note = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    order = relationship("OrderDB", back_populates="events")


# Alias để các router dùng tên ngắn
Product = ProductDB
Category = CategoryDB
User = UserDB
PasswordResetOTP = PasswordResetOTPDB
Order = OrderDB
OrderItem = OrderItemDB
OrderEvent = OrderEventDB
UserAvatar = UserAvatarDB