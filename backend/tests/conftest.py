"""测试环境：在导入 app 之前把数据库切到临时 sqlite 文件。"""
import os
import tempfile

_fd, _path = tempfile.mkstemp(suffix=".db", prefix="vendfill_test_")
os.close(_fd)
os.environ["DATABASE_URL"] = f"sqlite:///{_path}"
os.environ["SEED_ON_EMPTY"] = "false"

import pytest
from fastapi.testclient import TestClient

from app.database import Base, engine
from app.main import app
from app.models.models import Lane, Location


@pytest.fixture
def db_setup():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield


@pytest.fixture
def client(db_setup):
    with TestClient(app) as c:
        yield c


@pytest.fixture
def seeded_location(db_setup):
    """与 seed.py 同构的 A/B/C/D 立柱布局：D 立柱本批补量为 0。"""
    from app.database import SessionLocal
    db = SessionLocal()
    loc = Location(code="VM-01", name="测试点位", address="测试地址")
    db.add(loc)
    db.flush()
    for slot, sku, cap, stock, transit in [
        ("A1", "矿泉水", 20, 5, 0),     # 待补 15
        ("A2", "可乐", 18, 18, 0),      # 满仓
        ("B1", "薯片", 12, 3, 2),       # 待补 7
        ("B2", "巧克力", 15, 10, 5),    # 满仓
        ("C1", "能量棒", 10, 0, 0),     # 待补 10
        ("C2", "口香糖", 24, 24, 2),    # 超占
        ("D1", "坚果", 10, 10, 0),      # 满仓：D 补量 0
    ]:
        db.add(Lane(location_id=loc.id, slot_no=slot, sku_name=sku,
                    capacity=cap, stock=stock, in_transit=transit))
    db.commit()
    db.close()
    return 1
