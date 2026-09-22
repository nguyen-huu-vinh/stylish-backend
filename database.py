import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

# Đọc URL từ biến môi trường (Render sẽ tự cấp khi deploy)
DATABASE_URL = os.environ.get("DATABASE_URL")

if DATABASE_URL:
    # Đang chạy trên Render, dùng PostgreSQL
    # Render cấp URL dạng "postgres://", cần đổi thành "postgresql://" để SQLAlchemy hiểu
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
    engine = create_engine(DATABASE_URL)
else:
    # Đang chạy local, dùng SQLite như cũ
    DATABASE_URL = "sqlite:///./stylish.db"
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()