from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Float, Boolean
from sqlalchemy.orm import relationship
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


class UserDB(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    full_name = Column(String, nullable=True)
    is_admin = Column(Boolean, default=False)


class PasswordResetOTPDB(Base):
    __tablename__ = "password_reset_otps"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), unique=True, nullable=False)
    otp_hash = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    attempts = Column(Integer, default=0, nullable=False)


# Alias để các router dùng tên ngắn
Product = ProductDB
Category = CategoryDB
User = UserDB
PasswordResetOTP = PasswordResetOTPDB