import os
from typing import List, Optional
from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, FileResponse
from pydantic import BaseModel
from sqlalchemy import Column, Integer, String, Float, Boolean
from sqlalchemy.orm import Session
from passlib.context import CryptContext
from datetime import datetime, timedelta
from jose import JWTError, jwt

# --- DÙNG CHUNG CẤU HÌNH DATABASE TỪ database.py ---
# (Trước đây main.py tự tạo engine/Base riêng, khác với database.py —
#  điều này khiến 2 file trỏ tới 2 "MetaData" khác nhau và có thể tạo
#  bảng ở một DB nhưng lại đọc/ghi vào DB khác khi deploy. Import chung
#  1 nguồn duy nhất để tránh lệch dữ liệu.)
from database import engine, SessionLocal, Base

# --- CẤU HÌNH JWT & BẢO MẬT ---
# SECRET_KEY BẮT BUỘC lấy từ biến môi trường. Không hardcode trong source
# vì bất kỳ ai đọc được code (repo public, log, v.v.) cũng có thể tự ký
# token admin giả. Đặt biến môi trường SECRET_KEY trên Render / máy local
# (ví dụ: export SECRET_KEY="chuỗi-ngẫu-nhiên-dài-và-khó-đoán").
SECRET_KEY = os.getenv("SECRET_KEY")
if not SECRET_KEY:
    raise RuntimeError(
        "Thiếu biến môi trường SECRET_KEY. Hãy đặt SECRET_KEY trước khi chạy server "
        "(ví dụ: export SECRET_KEY=$(openssl rand -hex 32))."
    )

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24  # 1 ngày

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")

# --- MODEL CƠ SỞ DỮ LIỆU ---
class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    full_name = Column(String, nullable=True)
    is_admin = Column(Boolean, default=False)

class Product(Base):
    __tablename__ = "products"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    price = Column(Float, nullable=False)
    discount_price = Column(Float, nullable=True)
    image_url = Column(String, nullable=True)
    is_sale = Column(Boolean, default=False)
    is_trending = Column(Boolean, default=False)

Base.metadata.create_all(bind=engine)

# --- PYDANTIC SCHEMAS ---
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
        orm_mode = True

# --- APP FASTAPI ---
app = FastAPI(title="E-Commerce API")

# CORS: liệt kê rõ domain được phép gọi API (thay "*" bằng domain thật của
# admin panel / web nếu có). Giữ "*" tạm thời cho Flutter mobile (không có
# "origin" trình duyệt) nhưng KHÔNG dùng allow_credentials=True cùng "*"
# vì tổ hợp này không an toàn và nhiều trình duyệt sẽ tự chặn.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Helper Functions
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password):
    return pwd_context.hash(password)

def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email: str = payload.get("sub")
        if email is None:
            raise HTTPException(status_code=401, detail="Token không hợp lệ")
    except JWTError:
        raise HTTPException(status_code=401, detail="Token không hợp lệ")

    user = db.query(User).filter(User.email == email).first()
    if user is None:
        raise HTTPException(status_code=404, detail="User không tồn tại")
    return user

def get_current_admin(current_user: User = Depends(get_current_user)):
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Bạn không có quyền Admin")
    return current_user

# Tạo sẵn tài khoản Admin mặc định nếu chưa có.
# Lấy email/mật khẩu admin từ biến môi trường ADMIN_EMAIL / ADMIN_PASSWORD
# nếu có; nếu không, dùng giá trị mặc định (chỉ nên dùng khi chạy local).
@app.on_event("startup")
def startup_db_check():
    db = SessionLocal()
    admin_email = os.getenv("ADMIN_EMAIL", "admin@gmail.com")
    admin_password = os.getenv("ADMIN_PASSWORD", "Admin123456")
    if not os.getenv("ADMIN_EMAIL") or not os.getenv("ADMIN_PASSWORD"):
        print(
            "[CẢNH BÁO] Đang dùng tài khoản admin mặc định "
            f"({admin_email}). Đặt biến môi trường ADMIN_EMAIL và "
            "ADMIN_PASSWORD để dùng thông tin đăng nhập riêng khi deploy thật."
        )

    admin = db.query(User).filter(User.email == admin_email).first()
    if not admin:
        admin_user = User(
            email=admin_email,
            hashed_password=get_password_hash(admin_password),
            full_name="Administrator",
            is_admin=True,
        )
        db.add(admin_user)
        db.commit()
    db.close()

# --- ENDPOINTS GIAO DIỆN WEB ADMIN ---
@app.get("/admin", response_class=HTMLResponse)
def get_admin_page():
    if os.path.exists("admin.html"):
        return FileResponse("admin.html")
    return "<h1>Chưa tìm thấy file admin.html!</h1>"

# --- ENDPOINTS AUTH & ĐĂNG KÝ (Dùng cho Flutter & Web) ---
@app.post("/register", status_code=201)
def register(user_data: UserRegister, db: Session = Depends(get_db)):
    existing = db.query(User).filter(User.email == user_data.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email này đã được sử dụng!")

    if len(user_data.password) < 6:
        raise HTTPException(status_code=400, detail="Mật khẩu phải có ít nhất 6 ký tự!")

    new_user = User(
        email=user_data.email,
        hashed_password=get_password_hash(user_data.password),
        full_name=user_data.full_name,
        is_admin=False,
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return {"message": "Đăng ký tài khoản thành công!", "user_id": new_user.id}

@app.post("/login")
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == form_data.username).first()
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=400, detail="Email hoặc mật khẩu không chính xác")

    access_token = create_access_token(data={"sub": user.email})
    return {"access_token": access_token, "token_type": "bearer", "is_admin": user.is_admin}

# --- ENDPOINTS QUẢN LÝ TÀI KHOẢN (USER MANAGEMENT) ---
@app.get("/users")
def get_all_users(db: Session = Depends(get_db), current_admin: User = Depends(get_current_admin)):
    return db.query(User).all()

@app.post("/users")
def create_user_by_admin(user_data: UserRegister, db: Session = Depends(get_db), current_admin: User = Depends(get_current_admin)):
    existing = db.query(User).filter(User.email == user_data.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email đã tồn tại!")

    if len(user_data.password) < 6:
        raise HTTPException(status_code=400, detail="Mật khẩu phải có ít nhất 6 ký tự!")

    user = User(
        email=user_data.email,
        hashed_password=get_password_hash(user_data.password),
        full_name=user_data.full_name,
        is_admin=False,
    )
    db.add(user)
    db.commit()
    return {"message": "Thêm người dùng thành công"}

@app.put("/users/{user_id}")
def update_user(user_id: int, user_data: UserUpdate, db: Session = Depends(get_db), current_admin: User = Depends(get_current_admin)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Không tìm thấy tài khoản")

    if user_data.email is not None and user_data.email != user.email:
        # Kiểm tra email mới có bị trùng với người khác không, tránh lỗi
        # IntegrityError không rõ nguyên nhân khi commit.
        dup = db.query(User).filter(User.email == user_data.email).first()
        if dup:
            raise HTTPException(status_code=400, detail="Email này đã được người khác sử dụng!")
        user.email = user_data.email

    if user_data.full_name is not None:
        user.full_name = user_data.full_name
    if user_data.is_admin is not None:
        user.is_admin = user_data.is_admin

    db.commit()
    return {"message": "Cập nhật tài khoản thành công"}

@app.delete("/users/{user_id}")
def delete_user(user_id: int, db: Session = Depends(get_db), current_admin: User = Depends(get_current_admin)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Không tìm thấy tài khoản")
    if user.id == current_admin.id:
        raise HTTPException(status_code=400, detail="Không thể xóa tài khoản Admin đang đăng nhập!")

    db.delete(user)
    db.commit()
    return {"message": "Đã xóa tài khoản thành công"}

# --- ENDPOINTS QUẢN LÝ SẢN PHẨM (PRODUCT MANAGEMENT) ---
@app.get("/products")
def get_products(db: Session = Depends(get_db)):
    return db.query(Product).all()

@app.post("/products")
def create_product(product: ProductSchema, db: Session = Depends(get_db), current_admin: User = Depends(get_current_admin)):
    new_p = Product(**product.dict())
    db.add(new_p)
    db.commit()
    db.refresh(new_p)
    return new_p

@app.delete("/products/{product_id}")
def delete_product(product_id: int, db: Session = Depends(get_db), current_admin: User = Depends(get_current_admin)):
    p = db.query(Product).filter(Product.id == product_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Không tìm thấy sản phẩm")
    db.delete(p)
    db.commit()
    return {"message": "Đã xóa sản phẩm"}