from sqlalchemy import Column, Integer, String, Float, Boolean
from database import Base

class ProductDB(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    price = Column(Float)
    image_url = Column(String)
    is_trending = Column(Boolean, default=False)   # đánh dấu sản phẩm trending