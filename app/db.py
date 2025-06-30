import os
from sqlalchemy import (create_engine, MetaData, Table, Column,
                        Integer, String, DateTime, ForeignKey, func)

DB_DSN = os.getenv("DB_DSN", "mysql+pymysql://eanapp:eanpass@db/ean")
engine  = create_engine(DB_DSN, echo=False, future=True)
metadata = MetaData()

category = Table(
    "category", metadata,
    Column("id", Integer, primary_key=True),
    Column("name", String(100), unique=True, nullable=False),
)

product = Table(
    "product", metadata,
    Column("id", Integer, primary_key=True),
    Column("ean", String(32), unique=True, nullable=False),
    Column("name", String(255), nullable=False),
    Column("category_id", Integer, ForeignKey("category.id"), nullable=False),
    Column("brand_id",   Integer, ForeignKey("brand.id"),   nullable=True),
)

slip = Table(
    "slip", metadata,
    Column("id", Integer, primary_key=True),
    Column("number", String(30), unique=True, nullable=False),
    Column("order_no", String(30)),
    Column("customer", String(120)),
    Column("created_at", DateTime, server_default=func.now())
)

slip_item = Table(
    "slip_item", metadata,
    Column("id", Integer, primary_key=True),
    Column("slip_id", Integer, ForeignKey("slip.id"), nullable=False),
    Column("product_id", Integer, ForeignKey("product.id"), nullable=False),
    Column("quantity",   Integer, nullable=False, default=1),  # neu
)

serial = Table(
    "serial", metadata,
    Column("id", Integer, primary_key=True),
    Column("item_id", Integer, ForeignKey("slip_item.id"), nullable=False),
    Column("sn", String(100)),
)

brand = Table(
    "brand", metadata,
    Column("id", Integer, primary_key=True),
    Column("name", String(120), unique=True, nullable=False),
)

def init_db() -> None:
    metadata.create_all(engine)
