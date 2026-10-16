from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import func
from fastapi.middleware.cors import CORSMiddleware

import models  # noqa: F401  (phải import để create_all thấy các bảng)
from config import ADMIN_EMAIL, ADMIN_PASSWORD
from database import (
    engine,
    SessionLocal,
    Base,
    ensure_order_tracking_schema,
    ensure_product_category_schema,
)
from security import get_password_hash
from routers import (
    addresses,
    admin,
    auth,
    avatars,
    categories,
    coupons,
    devices,
    notifications,
    orders,
    products,
    reviews,
    tracking,
    users,
)

Base.metadata.create_all(bind=engine)
ensure_product_category_schema()
ensure_order_tracking_schema()

@asynccontextmanager
async def lifespan(_app: FastAPI):
    startup_db_check()
    yield


app = FastAPI(title="E-Commerce API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(avatars.router)
app.include_router(users.router)
app.include_router(products.router)
app.include_router(categories.router)
app.include_router(orders.router)
app.include_router(reviews.router)
app.include_router(addresses.router)
app.include_router(coupons.router)
app.include_router(devices.router)
app.include_router(notifications.router)
app.include_router(tracking.router)
app.include_router(admin.router)


@app.get("/health", tags=["Health"])
def health():
    return {"status": "ok"}


def startup_db_check():
    # Không có tài khoản admin mặc định: thiếu biến môi trường thì bỏ qua
    if not ADMIN_EMAIL or not ADMIN_PASSWORD:
        print("[CẢNH BÁO] Chưa đặt ADMIN_EMAIL/ADMIN_PASSWORD nên không tạo "
              "tài khoản admin.")
        return
    email = ADMIN_EMAIL.strip().lower()

    db = SessionLocal()
    try:
        if not db.query(models.User).filter(
            func.lower(models.User.email) == email
        ).first():
            db.add(models.User(
                email=email,
                hashed_password=get_password_hash(ADMIN_PASSWORD),
                full_name="Administrator",
                is_admin=True,
            ))
            db.commit()
    finally:
        db.close()

