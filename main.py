import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("stylish")


@app.middleware("http")
async def log_requests(request: Request, call_next):
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        # Lỗi không lường trước: ghi đủ stack trace, trả lỗi gọn cho client
        logger.exception("Unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=500, content={"detail": "Lỗi hệ thống, vui lòng thử lại sau"}
        )
    elapsed = (time.perf_counter() - started) * 1000
    if request.url.path != "/health":
        logger.info(
            "%s %s -> %s (%.0f ms)",
            request.method, request.url.path, response.status_code, elapsed,
        )
    return response


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

