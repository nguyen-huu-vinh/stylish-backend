import os
from contextlib import asynccontextmanager
from typing import List, Optional

from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.responses import HTMLResponse
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel, EmailStr
from sqlalchemy import text
from sqlalchemy.orm import Session
from passlib.context import CryptContext
import jwt

# Import từ các file trong cùng dự án
from database import engine, SessionLocal, Base
from models import ProductDB, UserDB

# Tạo các bảng trong Database
Base.metadata.create_all(bind=engine)

# Cấu hình bảo mật JWT
SECRET_KEY = os.getenv("SECRET_KEY", "super-secret-key-for-local-dev")
ALGORITHM = "HS256"

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")


# ---------- Schemas (Pydantic Models) ----------
class ProductCreate(BaseModel):
    name: str
    price: float
    discount_price: Optional[float] = None
    is_sale: bool = False
    image_url: str
    is_trending: bool = False


class ProductResponse(ProductCreate):
    id: int

    class Config:
        from_attributes = True


class UserCreate(BaseModel):
    email: EmailStr
    password: str
    full_name: str


class UserResponse(BaseModel):
    id: int
    email: EmailStr
    full_name: str
    is_admin: bool

    class Config:
        from_attributes = True


class Token(BaseModel):
    access_token: str
    token_type: str


# ---------- Hàm hỗ trợ DB & Auth ----------
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def create_access_token(data: dict):
    to_encode = data.copy()
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def get_current_user(
    token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)
):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Không thể xác thực thông tin đăng nhập",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email: str = payload.get("sub")
        if email is None:
            raise credentials_exception
    except jwt.PyJWTError:
        raise credentials_exception

    user = db.query(UserDB).filter(UserDB.email == email).first()
    if user is None:
        raise credentials_exception
    return user


def get_current_admin_user(current_user: UserDB = Depends(get_current_user)):
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Bạn không có quyền truy cập quản trị",
        )
    return current_user


# ---------- Seed dữ liệu & Khởi động ----------
@asynccontextmanager
async def lifespan(app: FastAPI):
    db = SessionLocal()
    try:
        # Tự động thêm cột mới vào PostgreSQL trên Render nếu bảng cũ chưa có
        try:
            db.execute(text("ALTER TABLE products ADD COLUMN IF NOT EXISTS discount_price FLOAT;"))
            db.execute(text("ALTER TABLE products ADD COLUMN IF NOT EXISTS is_sale BOOLEAN DEFAULT FALSE;"))
            db.commit()
        except Exception:
            db.rollback()

        # Khởi tạo dữ liệu sản phẩm mẫu nếu chưa có
        if db.query(ProductDB).count() == 0:
            db.add_all(
                [
                    ProductDB(
                        name="Áo thun trắng",
                        price=199000,
                        image_url="https://picsum.photos/id/1/300/300",
                        is_trending=False,
                    ),
                    ProductDB(
                        name="Quần jeans",
                        price=450000,
                        discount_price=390000,
                        is_sale=True,
                        image_url="https://picsum.photos/id/2/300/300",
                        is_trending=False,
                    ),
                    ProductDB(
                        name="Váy hoa",
                        price=320000,
                        image_url="https://picsum.photos/id/3/300/300",
                        is_trending=True,
                    ),
                    ProductDB(
                        name="Túi xách",
                        price=280000,
                        discount_price=220000,
                        is_sale=True,
                        image_url="https://picsum.photos/id/4/300/300",
                        is_trending=True,
                    ),
                ]
            )
            db.commit()

        # Tạo tài khoản Admin mặc định từ biến môi trường
        admin_email = os.getenv("ADMIN_EMAIL")
        admin_password = os.getenv("ADMIN_PASSWORD")
        if admin_email and admin_password:
            admin_email = admin_email.lower().strip()
            if not db.query(UserDB).filter(UserDB.email == admin_email).first():
                db.add(
                    UserDB(
                        email=admin_email,
                        hashed_password=pwd_context.hash(admin_password),
                        full_name="Admin",
                        is_admin=True,
                    )
                )
                db.commit()
    finally:
        db.close()
    yield


app = FastAPI(title="Stylish App", lifespan=lifespan)


# ---------- API Auth ----------
@app.post("/register", response_model=UserResponse)
def register(user_data: UserCreate, db: Session = Depends(get_db)):
    email_clean = user_data.email.lower().strip()
    if db.query(UserDB).filter(UserDB.email == email_clean).first():
        raise HTTPException(
            status_code=400, detail="Email này đã được đăng ký"
        )

    new_user = UserDB(
        email=email_clean,
        hashed_password=pwd_context.hash(user_data.password),
        full_name=user_data.full_name,
        is_admin=False,
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return new_user


@app.post("/token", response_model=Token)
def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    email_clean = form_data.username.lower().strip()
    user = db.query(UserDB).filter(UserDB.email == email_clean).first()
    if not user or not pwd_context.verify(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=400, detail="Email hoặc mật khẩu không chính xác"
        )

    access_token = create_access_token(data={"sub": user.email})
    return {"access_token": access_token, "token_type": "bearer"}


# ---------- API Products ----------
@app.get("/products", response_model=List[ProductResponse])
def get_products(db: Session = Depends(get_db)):
    return db.query(ProductDB).all()


@app.post(
    "/products",
    response_model=ProductResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_product(
    product: ProductCreate,
    db: Session = Depends(get_db),
    admin: UserDB = Depends(get_current_admin_user),
):
    new_product = ProductDB(**product.model_dump())
    db.add(new_product)
    db.commit()
    db.refresh(new_product)
    return new_product


@app.put("/products/{product_id}", response_model=ProductResponse)
def update_product(
    product_id: int,
    product_data: ProductCreate,
    db: Session = Depends(get_db),
    admin: UserDB = Depends(get_current_admin_user),
):
    product = db.query(ProductDB).filter(ProductDB.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Không tìm thấy sản phẩm")

    for key, value in product_data.model_dump().items():
        setattr(product, key, value)

    db.commit()
    db.refresh(product)
    return product


@app.delete("/products/{product_id}")
def delete_product(
    product_id: int,
    db: Session = Depends(get_db),
    admin: UserDB = Depends(get_current_admin_user),
):
    product = db.query(ProductDB).filter(ProductDB.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Không tìm thấy sản phẩm")

    db.delete(product)
    db.commit()
    return {"message": "Đã xóa sản phẩm thành công"}


# ---------- Route Trang Admin HTML ----------
@app.get("/admin", response_class=HTMLResponse)
def get_admin_page():
    if os.path.exists("admin.html"):
        with open("admin.html", "r", encoding="utf-8") as f:
            return f.read()
    return "<h1>Trang admin.html không tồn tại trong thư mục gốc.</h1>"