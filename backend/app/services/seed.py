from datetime import datetime, timedelta
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from app.models.models import Lane, Location, Sale

def seed_if_empty(db: Session) -> None:
    if (db.scalar(select(func.count()).select_from(Location)) or 0) > 0:
        return
    loc = Location(code="VM-01", name="地铁口 A 点位", address="城东地铁 1 号口")
    db.add(loc); db.flush()
    lanes = [
        ("A1", "矿泉水", 20, 5, 0),    # 待补 15
        ("A2", "可乐", 18, 18, 0),     # 满仓
        ("B1", "薯片", 12, 3, 2),      # 待补 7
        ("B2", "巧克力", 15, 10, 5),   # 满仓
        ("C1", "能量棒", 10, 0, 0),    # 待补 10
        ("C2", "口香糖", 24, 24, 2),   # 超占
        ("D1", "坚果", 10, 10, 0),     # 满仓：D 立柱本批补量 0，不建空单但字母键保留
    ]
    lane_ids = []
    for slot, sku, cap, stock, transit in lanes:
        lane = Lane(location_id=loc.id, slot_no=slot, sku_name=sku, capacity=cap, stock=stock, in_transit=transit)
        db.add(lane); db.flush()
        lane_ids.append(lane.id)
    now = datetime(2026, 9, 16, 12, 0, 0)
    for i, lid in enumerate(lane_ids):
        db.add(Sale(lane_id=lid, qty=2 + i, sold_at=now - timedelta(hours=i)))
    db.commit()
