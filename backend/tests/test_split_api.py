"""API-level tests for the letter-split refill run.

Uses an in-memory SQLite db via dependency override; the app lifespan (which
would seed against Postgres) is not run because TestClient is not entered as a
context manager.
"""
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.api.refills as refills_mod
from app.database import Base, get_db
from app.main import app
from app.models.models import Lane, Location, RefillOrder, RefillSheet
from app.services.fill_engine import SplitError, line_to_dict
from app.services.seed import seed_if_empty

engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                       poolclass=StaticPool)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def _override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture()
def db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def client(db):
    app.dependency_overrides[get_db] = _override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


def _make_machine(db):
    loc = Location(code="VM-T", name="测试点位")
    db.add(loc)
    db.flush()
    for slot, sku, cap, stock, tr in [
        ("A1", "水", 10, 5, 0),     # 待补 5
        ("A2", "可乐", 10, 10, 0),  # 满仓
        ("B1", "薯片", 8, 3, 0),    # 待补 5
        ("C1", "饼干", 6, 6, 0),    # 满仓 → C 字母补量 0
    ]:
        db.add(Lane(location_id=loc.id, slot_no=slot, sku_name=sku,
                    capacity=cap, stock=stock, in_transit=tr))
    db.commit()
    return loc


def _counts(db):
    orders = db.scalar(select(func.count()).select_from(RefillOrder))
    sheets = db.scalar(select(func.count()).select_from(RefillSheet))
    return orders, sheets


def test_run_splits_into_letter_sheets(client, db):
    _make_machine(db)
    res = client.post("/api/refills/run?location_id=1")
    assert res.status_code == 200
    data = res.json()
    # 每个有待补的字母各落一张分册；C 无待补 → 不建空单但字母键保留
    assert [s["letter"] for s in data["sheets"]] == ["A", "B"]
    assert data["letters"] == {"A": 5, "B": 5, "C": 0}
    # 逐行货道与字母一致：A 组行不得写进 B 组单
    for sheet in data["sheets"]:
        assert sheet["lines"], "分册不得为空"
        assert all(l["letter"] == sheet["letter"] for l in sheet["lines"])
        assert all(l["slot_no"][0].upper() == sheet["letter"] for l in sheet["lines"])
        assert sheet["total_fill"] == sum(l["fill_qty"] for l in sheet["lines"])
    # 各分册之和 = 整机总补件数
    assert data["sheets_total"] == data["total_fill"] == 10
    assert sum(data["letters"].values()) == 10
    # 落库：1 批次 + 2 分册
    assert _counts(db) == (1, 2)


def test_summary_balances_and_explains_zero_letter(client, db):
    _make_machine(db)
    client.post("/api/refills/run?location_id=1")
    s = client.get("/api/refills/summary?location_id=1").json()
    assert s["balanced"] is True
    assert s["sheets_total"] == s["total_fill"] == s["letters_total"] == 10
    assert s["letters"]["C"] == 0  # 0 补量字母仍在台账中
    assert [sh["letter"] for sh in s["sheets"]] == ["A", "B"]


def test_run_rolls_back_half_written_sheets(client, db, monkeypatch):
    _make_machine(db)

    def boom(db_session, location_id, lines, sheets, letter_totals):
        # 模拟写完第一本分册后崩溃
        first = sheets[0]
        db_session.add(RefillSheet(
            order_id=999, location_id=location_id, group_letter=first.letter,
            total_fill=first.total_fill,
            lines_json=json.dumps([line_to_dict(l) for l in first.lines],
                                  ensure_ascii=False)))
        db_session.flush()
        raise RuntimeError("disk full")

    monkeypatch.setattr(refills_mod, "_persist_batch", boom)
    res = client.post("/api/refills/run?location_id=1")
    assert res.status_code == 500
    assert _counts(db) == (0, 0)  # 半套分册全部回滚，无任何残留


def test_run_voided_when_reconcile_fails(client, db, monkeypatch):
    _make_machine(db)

    def bad_reconcile(*_args):
        raise SplitError("forced imbalance")

    monkeypatch.setattr(refills_mod, "reconcile_split", bad_reconcile)
    res = client.post("/api/refills/run?location_id=1")
    assert res.status_code == 500
    assert "作废" in res.json()["detail"]
    assert _counts(db) == (0, 0)  # 对不齐即废：任何分册都不得落库


def test_history_keeps_original_attribution_after_rename(client, db):
    _make_machine(db)
    run = client.post("/api/refills/run?location_id=1").json()
    sheet_a = next(s for s in run["sheets"] if s["letter"] == "A")
    lane_a1 = db.scalars(select(Lane).where(Lane.slot_no == "A1")).one()

    # 生成成功后改货道编号字母 A1 -> Z1
    res = client.patch(f"/api/lanes/{lane_a1.id}", json={"slot_no": "Z1"})
    assert res.status_code == 200
    assert res.json()["slot_no"] == "Z1"

    # 打开历史分册：归属不得被现算改口
    hist = client.get(f"/api/refills/sheets/{sheet_a['id']}").json()
    assert hist["letter"] == "A"
    assert {l["slot_no"] for l in hist["lines"]} == {"A1", "A2"}
    assert all(l["letter"] == "A" for l in hist["lines"])
    assert hist["total_fill"] == 5

    # 历史批次的汇总台账也不变口
    s = client.get("/api/refills/summary?location_id=1").json()
    assert s["letters"] == {"A": 5, "B": 5, "C": 0}

    # 新一轮生成才按现名重新分组（Z 组出现；A 组只剩满仓的 A2 → 无 A 分册，
    # 但 A 字母键仍以补量 0 留在台账中，不得 silently 丢掉）
    rerun = client.post("/api/refills/run?location_id=1").json()
    assert rerun["letters"] == {"A": 0, "B": 5, "C": 0, "Z": 5}
    assert [sh["letter"] for sh in rerun["sheets"]] == ["B", "Z"]


def test_seed_produces_at_least_groups_a_and_b(client, db):
    seed_if_empty(db)
    res = client.post("/api/refills/run?location_id=1")
    assert res.status_code == 200
    data = res.json()
    letters = [s["letter"] for s in data["sheets"]]
    assert "A" in letters and "B" in letters
    for sheet in data["sheets"]:
        assert all(l["slot_no"][0].upper() == sheet["letter"] for l in sheet["lines"])
    s = client.get("/api/refills/summary?location_id=1").json()
    assert s["balanced"] is True
    assert s["sheets_total"] == s["total_fill"]
    assert s["letters"]["D"] == 0  # 全满字母组：无分册但台账有键
    assert "D" not in letters
