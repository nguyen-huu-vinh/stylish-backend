from typing import Optional
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