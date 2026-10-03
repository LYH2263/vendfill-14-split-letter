from datetime import datetime
from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base

class Location(Base):
    __tablename__ = "locations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(128))
    address: Mapped[str] = mapped_column(String(256), default="")

class Lane(Base):
    __tablename__ = "lanes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    location_id: Mapped[int] = mapped_column(ForeignKey("locations.id"))
    slot_no: Mapped[str] = mapped_column(String(16))
    sku_name: Mapped[str] = mapped_column(String(64))
    capacity: Mapped[int] = mapped_column(Integer)
    stock: Mapped[int] = mapped_column(Integer, default=0)
    in_transit: Mapped[int] = mapped_column(Integer, default=0)

class Sale(Base):
    __tablename__ = "sales"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lane_id: Mapped[int] = mapped_column(ForeignKey("lanes.id"))
    qty: Mapped[int] = mapped_column(Integer)
    sold_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class RefillRun(Base):
    """一次整机补货生成：整机汇总 + 全部货道行 + 各立柱字母分册统计的快照。

    数据落库后即为历史事实，不随货道当前状态重算（见 app.api.refills）。
    """
    __tablename__ = "refill_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    location_id: Mapped[int] = mapped_column(ForeignKey("locations.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    total_fill: Mapped[int] = mapped_column(Integer, default=0)
    need_fill_count: Mapped[int] = mapped_column(Integer, default=0)
    full_count: Mapped[int] = mapped_column(Integer, default=0)
    overbooked_count: Mapped[int] = mapped_column(Integer, default=0)
    # 整机全部货道行快照（含 column_key），JSON
    lines_json: Mapped[str] = mapped_column(Text, default="[]")
    # 各立柱字母统计快照（含补量为 0 的字母，键不得丢），JSON
    columns_json: Mapped[str] = mapped_column(Text, default="[]")

class RefillOrder(Base):
    """立柱字母分册补货单：一个 RefillRun 下每个有待补货道的字母一册。

    lines_json 为生成瞬间的行快照，历史分册只认快照，不按当前货道重新计算。
    无待补货道的字母允许不建册（不出空单），但其字母键保留在 RefillRun.columns_json。
    """
    __tablename__ = "refill_orders"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("refill_runs.id"))
    location_id: Mapped[int] = mapped_column(ForeignKey("locations.id"))
    column_key: Mapped[str] = mapped_column(String(8))
    total_fill: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    lines_json: Mapped[str] = mapped_column(Text, default="[]")

    __table_args__ = (
        UniqueConstraint("run_id", "column_key", name="uq_refill_run_column"),
    )
