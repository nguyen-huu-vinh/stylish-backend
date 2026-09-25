import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import jwt
from fastapi import FastAPI, HTTPException, Depends
from fastapi.responses import FileResponse
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from passlib.context import CryptContext
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from database import engine, SessionLocal, Base
from models import ProductDB, UserDB

Base.metadata.create_all(bind=engine)

# ---------- Cấu hình bảo mật ----------
SECRET_KEY = os.getenv("SECRET_KEY", "dev-only-change-me")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/login")

DUMMY_HASH = pwd_context.hash("dummy-password")


# ---------- Seed dữ liệu khi khởi động ----------
@asynccontextmanager
async def lifespan(app: FastAPI):
    db = SessionLocal()
    try:
        if db.query(ProductDB).count() == 0:
            db.add_all([
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
            ])
            db.commit()

        admin_email = os.getenv("ADMIN_EMAIL")
        admin_password = os.getenv("ADMIN_PASSWORD")
        if admin_email and admin_password:
            admin_email = admin_email.lower().strip()
            if not db.query(UserDB).filter(UserDB.email == admin_email).first():
                db.add(UserDB(
                    email=admin_email,
                    hashed_password=pwd_context.hash(admin_password),
                    full_name="Admin",
                    is_admin=True,
                ))
                db.commit()
    finally:
        db.close()
    yield


app = FastAPI(lifespan=lifespan)


# ---------- Schemas ----------
class ProductCreate(BaseModel):
    name: str
    price: float
    discount_price: Optional[float] = None
    is_sale: bool = False
    image_url: str
    is_trending: bool = False


class ProductUpdate(BaseModel):
    name: Optional[str] = None
    price: Optional[float] = None
    discount_price: Optional[float] = None
    is_sale: Optional[bool] = None
    image_url: Optional[str] = None
    is_trending: Optional[bool] = None


class ProductOut(ProductCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int


class UserRegister(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)
    full_name: Optional[str] = None


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    full_name: Optional[str] = None
    is_admin: bool


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class AdminUserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)
    full_name: Optional[str] = None
    is_admin: bool = False


class AdminUserUpdate(BaseModel):
    is_admin: Optional[bool] = None
    password: Optional[str] = Field(default=None, min_length=8, max_length=72)


# ---------- Dependencies ----------
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def create_access_token(user_id: int) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {"sub": str(user_id), "exp": expire}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> UserDB:
    credentials_error = HTTPException(
        status_code=401,
        detail="Token không hợp lệ hoặc đã hết hạn",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = int(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        raise credentials_error

    user = db.get(UserDB, user_id)
    if user is None:
        raise credentials_error
    return user


def require_admin(user: UserDB = Depends(get_current_user)) -> UserDB:
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Chỉ admin mới có quyền thực hiện")
    return user


# ---------- Products API ----------
@app.get("/products", response_model=list[ProductOut])
def get_products(db: Session = Depends(get_db)):
    return db.query(ProductDB).filter(ProductDB.is_trending == False).all()


@app.get("/trending", response_model=list[ProductOut])
def get_trending(db: Session = Depends(get_db)):
    return db.query(ProductDB).filter(ProductDB.is_trending == True).all()


@app.get("/sale", response_model=list[ProductOut])
def get_sale_products(db: Session = Depends(get_db)):
    return db.query(ProductDB).filter(ProductDB.is_sale == True).all()


@app.get("/admin/products", response_model=list[ProductOut])
def admin_get_all_products(
    db: Session = Depends(get_db),
    _admin: UserDB = Depends(require_admin),
):
    return db.query(ProductDB).order_by(ProductDB.id).all()


@app.get("/products/{product_id}", response_model=ProductOut)
def get_product(product_id: int, db: Session = Depends(get_db)):
    product = db.get(ProductDB, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Không tìm thấy sản phẩm")
    return product


@app.post("/products", response_model=ProductOut)
def create_product(
    product: ProductCreate,
    db: Session = Depends(get_db),
    _admin: UserDB = Depends(require_admin),
):
    new_product = ProductDB(**product.model_dump())
    db.add(new_product)
    db.commit()
    db.refresh(new_product)
    return new_product


@app.patch("/products/{product_id}", response_model=ProductOut)
def update_product(
    product_id: int,
    data: ProductUpdate,
    db: Session = Depends(get_db),
    _admin: UserDB = Depends(require_admin),
):
    product = db.get(ProductDB, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Không tìm thấy sản phẩm")

    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(product, key, value)

    db.commit()
    db.refresh(product)
    return product


@app.delete("/products/{product_id}")
def delete_product(
    product_id: int,
    db: Session = Depends(get_db),
    _admin: UserDB = Depends(require_admin),
):
    product = db.get(ProductDB, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Không tìm thấy sản phẩm")
    db.delete(product)
    db.commit()
    return {"message": "Đã xóa sản phẩm"}


# ---------- Admin: Trang quản trị ----------
ADMIN_PAGE = Path(__file__).parent / "admin.html"


@app.get("/admin", include_in_schema=False)
def admin_page():
    return FileResponse(ADMIN_PAGE)


# ---------- Admin: Quản lý tài khoản ----------
@app.get("/admin/users", response_model=list[UserOut])
def admin_list_users(
    db: Session = Depends(get_db),
    _admin: UserDB = Depends(require_admin),
):
    return db.query(UserDB).order_by(UserDB.id).all()


@app.post("/admin/users", response_model=UserOut, status_code=201)
def admin_create_user(
    data: AdminUserCreate,
    db: Session = Depends(get_db),
    _admin: UserDB = Depends(require_admin),
):
    email = data.email.lower().strip()
    if db.query(UserDB).filter(UserDB.email == email).first():
        raise HTTPException(status_code=400, detail="Email đã được đăng ký")
    user = UserDB(
        email=email,
        hashed_password=pwd_context.hash(data.password),
        full_name=data.full_name,
        is_admin=data.is_admin,
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="Email đã được đăng ký")
    db.refresh(user)
    return user


@app.patch("/admin/users/{user_id}", response_model=UserOut)
def admin_update_user(
    user_id: int,
    data: AdminUserUpdate,
    db: Session = Depends(get_db),
    admin: UserDB = Depends(require_admin),
):
    user = db.get(UserDB, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Không tìm thấy tài khoản")
    if data.is_admin is not None:
        if user.id == admin.id and not data.is_admin:
            raise HTTPException(status_code=400, detail="Không thể tự bỏ quyền admin của mình")
        user.is_admin = data.is_admin
    if data.password is not None:
        user.hashed_password = pwd_context.hash(data.password)
    db.commit()
    db.refresh(user)
    return user


@app.delete("/admin/users/{user_id}")
def admin_delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    admin: UserDB = Depends(require_admin),
):
    user = db.get(UserDB, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Không tìm thấy tài khoản")
    if user.id == admin.id:
        raise HTTPException(status_code=400, detail="Không thể tự xoá tài khoản của mình")
    db.delete(user)
    db.commit()
    return {"message": "Đã xóa tài khoản"}


# ---------- Auth ----------
@app.get("/me", response_model=UserOut)
def read_me(current_user: UserDB = Depends(get_current_user)):
    return current_user


@app.post("/register", response_model=UserOut, status_code=201)
def register(user: UserRegister, db: Session = Depends(get_db)):
    email = user.email.lower().strip()

    if db.query(UserDB).filter(UserDB.email == email).first():
        raise HTTPException(status_code=400, detail="Email đã được đăng ký")

    new_user = UserDB(
        email=email,
        hashed_password=pwd_context.hash(user.password),
        full_name=user.full_name,
    )
    db.add(new_user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="Email đã được đăng ký")
    db.refresh(new_user)
    return new_user


@app.post("/login", response_model=Token)
def login(
    form: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    email = form.username.lower().strip()
    user = db.query(UserDB).filter(UserDB.email == email).first()

    hashed = user.hashed_password if user else DUMMY_HASH
    password_ok = pwd_context.verify(form.password, hashed)

    if not user or not password_ok:
        raise HTTPException(
            status_code=401,
            detail="Email hoặc mật khẩu không đúng",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return Token(access_token=create_access_token(user.id))