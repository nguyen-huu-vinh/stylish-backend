from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import models  # noqa: F401  (phải import để create_all thấy các bảng)
from config import ADMIN_EMAIL, ADMIN_PASSWORD
from database import engine, SessionLocal, Base
from security import get_password_hash
from routers import auth, users, products, admin

Base.metadata.create_all(bind=engine)

app = FastAPI(title="E-Commerce API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(users.router)
app.include_router(products.router)
app.include_router(admin.router)


@app.on_event("startup")
def startup_db_check():
    email = ADMIN_EMAIL or "admin@gmail.com"
    password = ADMIN_PASSWORD or "Admin123456"
    if not ADMIN_EMAIL or not ADMIN_PASSWORD:
        print(f"[CẢNH BÁO] Đang dùng tài khoản admin mặc định ({email}). "
              "Đặt ADMIN_EMAIL và ADMIN_PASSWORD khi deploy thật.")

    db = SessionLocal()
    try:
        if not db.query(models.User).filter(models.User.email == email).first():
            db.add(models.User(
                email=email,
                hashed_password=get_password_hash(password),
                full_name="Administrator",
                is_admin=True,
            ))
            db.commit()
    finally:
        db.close()