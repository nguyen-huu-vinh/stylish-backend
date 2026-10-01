from typing import Optional
from pydantic import BaseModel


class UserRegister(BaseModel):
    email: str
    password: str
    full_name: Optional[str] = None


class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    email: Optional[str] = None
    is_admin: Optional[bool] = None


class ProductSchema(BaseModel):
    name: str
    price: float
    discount_price: Optional[float] = None
    image_url: Optional[str] = None
    is_sale: bool = False
    is_trending: bool = False

    class Config:
        model_config = {"from_attributes": True}