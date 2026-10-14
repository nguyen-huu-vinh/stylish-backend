import os
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker, declarative_base

# Đọc URL từ biến môi trường (Render sẽ tự cấp khi deploy)
DATABASE_URL = os.environ.get("DATABASE_URL")

if DATABASE_URL:
    # Đang chạy trên Render, dùng PostgreSQL
    # Render cấp URL dạng "postgres://", cần đổi thành "postgresql://" để SQLAlchemy hiểu
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
    engine = create_engine(
        DATABASE_URL,
        pool_pre_ping=True,
        connect_args={"connect_timeout": 10},
    )
else:
    # Đang chạy local, dùng SQLite như cũ
    DATABASE_URL = "sqlite:///./stylish.db"
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def ensure_order_tracking_schema():
    """Thêm các cột theo dõi bản đồ vào bảng orders đã có sẵn trên server."""
    Base.metadata.create_all(bind=engine)

    new_columns = {
        "delivery_lat": "FLOAT",
        "delivery_lng": "FLOAT",
        "geocoded": "BOOLEAN DEFAULT FALSE",
        "shipper_lat": "FLOAT",
        "shipper_lng": "FLOAT",
        "shipper_updated_at": "TIMESTAMP",
        "tracking_token": "VARCHAR",
    }
    with engine.begin() as connection:
        columns = {
            column["name"]
            for column in inspect(connection).get_columns("orders")
        }
        for name, column_type in new_columns.items():
            if name not in columns:
                connection.execute(
                    text(f"ALTER TABLE orders ADD COLUMN {name} {column_type}")
                )
        item_columns = {
            column["name"]
            for column in inspect(connection).get_columns("order_items")
        }
        if "stock_deducted" not in item_columns:
            connection.execute(
                text(
                    "ALTER TABLE order_items ADD COLUMN "
                    "stock_deducted BOOLEAN NOT NULL DEFAULT FALSE"
                )
            )


def ensure_product_category_schema():
    from models import Category, Product

    Base.metadata.create_all(bind=engine)

    with engine.begin() as connection:
        columns = {
            column["name"]
            for column in inspect(connection).get_columns("products")
        }
        if "category_id" not in columns:
            connection.execute(
                text(
                    "ALTER TABLE products ADD COLUMN category_id INTEGER "
                    "REFERENCES categories(id)"
                )
            )
        if "description" not in columns:
            connection.execute(
                text("ALTER TABLE products ADD COLUMN description VARCHAR")
            )
        if "is_deal_of_the_day" not in columns:
            connection.execute(
                text(
                    "ALTER TABLE products ADD COLUMN "
                    "is_deal_of_the_day BOOLEAN DEFAULT FALSE"
                )
            )
        if "is_new" not in columns:
            connection.execute(
                text("ALTER TABLE products ADD COLUMN is_new BOOLEAN DEFAULT FALSE")
            )
        if "stock" not in columns:
            connection.execute(text("ALTER TABLE products ADD COLUMN stock INTEGER"))
        if "sizes" not in columns:
            connection.execute(text("ALTER TABLE products ADD COLUMN sizes VARCHAR"))

    product_columns = {
        column["name"]
        for column in inspect(engine).get_columns("products")
    }
    defaults = ("Beauty", "Fashion", "Kids", "Mens", "Womens")
    with SessionLocal() as session:
        categories_by_name = {
            category.name.casefold(): category
            for category in session.query(Category).all()
        }
        for name in defaults:
            if name.casefold() not in categories_by_name:
                category = Category(name=name)
                session.add(category)
                categories_by_name[name.casefold()] = category
        session.flush()

        if "category" in product_columns:
            legacy_products = session.execute(
                text(
                    "SELECT id, category FROM products "
                    "WHERE category IS NOT NULL AND category_id IS NULL"
                )
            ).all()
            for product_id, category_name in legacy_products:
                category = categories_by_name.get(category_name.casefold())
                if category is None:
                    category = Category(name=category_name.strip())
                    session.add(category)
                    session.flush()
                    categories_by_name[category.name.casefold()] = category
                session.query(Product).filter(Product.id == product_id).update(
                    {Product.category_id: category.id}
                )
        session.commit()