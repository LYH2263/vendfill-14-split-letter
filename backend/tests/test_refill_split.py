"""端到端：原子生成、历史快照不可变、汇总对账、失败全回滚、种子 A/B 两组。"""
from app.database import SessionLocal
from app.models.models import Lane, RefillOrder, RefillRun


def test_run_creates_one_order_per_pending_column(client, seeded_location):
    r = client.post("/api/refills/run", params={"location_id": 1})
    assert r.status_code == 200, r.text
    data = r.json()

    # A 15 + B 7 + C 10 = 32；D 满仓补量 0
    assert data["total_fill"] == 32
    keys = [c["column_key"] for c in data["columns"]]
    assert keys == ["A", "B", "C", "D"]  # D 键不得丢

    pending = {c["column_key"]: c for c in data["columns"] if c["has_pending"]}
    assert set(pending) == {"A", "B", "C"}

    # 有待补的字母各有分册 id；D 无空单
    assert pending["A"]["order_id"] is not None
    assert pending["B"]["order_id"] is not None
    assert pending["C"]["order_id"] is not None
    d = next(c for c in data["columns"] if c["column_key"] == "D")
    assert d["order_id"] is None and d["total_fill"] == 0

    # 每个分册只含本字母货道（A 组行不得写进 B 组单）
    for c in data["columns"]:
        if c["order_id"] is None:
            continue
        order = client.get(f"/api/refills/orders/{c['order_id']}").json()
        assert order["column_key"] == c["column_key"]
        assert all(l["slot_no"].startswith(c["column_key"]) for l in order["lines"])
        assert order["total_fill"] == c["total_fill"]
        if c["column_key"] == "A":
            assert {l["slot_no"] for l in order["lines"]} == {"A1", "A2"}

    # 各分册之和 == 整机
    assert sum(c["total_fill"] for c in data["columns"]) == data["total_fill"] == 32

    db = SessionLocal()
    try:
        assert db.query(RefillRun).count() == 1
        assert sorted(o.column_key for o in db.query(RefillOrder).all()) == ["A", "B", "C"]
    finally:
        db.close()


def test_summary_reconciles_and_keeps_zero_column(client, seeded_location):
    client.post("/api/refills/run", params={"location_id": 1})
    s = client.get("/api/refills/summary", params={"location_id": 1}).json()
    assert s["total_fill"] == 32
    assert [c["column_key"] for c in s["columns"]] == ["A", "B", "C", "D"]
    # 汇总页按点位可见各分册补量，相加无漏无重
    assert sum(c["total_fill"] for c in s["columns"]) == s["total_fill"]
    by = {c["column_key"]: c for c in s["columns"]}
    assert by["A"]["total_fill"] == 15
    assert by["B"]["total_fill"] == 7
    assert by["C"]["total_fill"] == 10
    assert by["D"]["total_fill"] == 0 and by["D"]["order_id"] is None


def test_history_is_immutable_after_slot_rename(client, seeded_location):
    run = client.post("/api/refills/run", params={"location_id": 1}).json()
    run_id = run["id"]
    a1_order_id = next(c["order_id"] for c in run["columns"] if c["column_key"] == "A")

    # 事后把 A1 改成 X1（换立柱字母）
    db = SessionLocal()
    lane = db.query(Lane).filter(Lane.slot_no == "A1").one()
    lane.slot_no = "X1"
    db.commit()
    db.close()

    hist = client.get(f"/api/refills/runs/{run_id}").json()
    order = client.get(f"/api/refills/orders/{a1_order_id}").json()

    # 历史分册仍归属 A，行仍是 A1，不被现算改口
    hist_keys = {c["column_key"]: c for c in hist["columns"]}
    assert set(hist_keys) == {"A", "B", "C", "D"}
    assert hist_keys["A"]["total_fill"] == 15
    a_lines = {l["slot_no"]: l["column_key"] for l in hist_keys["A"]["lines"]}
    assert a_lines == {"A1": "A", "A2": "A"}
    assert order["column_key"] == "A"
    assert {l["slot_no"] for l in order["lines"]} == {"A1", "A2"}
    assert sum(c["total_fill"] for c in hist["columns"]) == hist["total_fill"] == 32

    # 重新生成才反映当前布局：新批次出现 X，历史批次不动
    new_run = client.post("/api/refills/run", params={"location_id": 1}).json()
    assert new_run["id"] != run_id
    new_keys = {c["column_key"]: c for c in new_run["columns"]}
    assert "X" in new_keys and "A" in new_keys
    hist_again = client.get(f"/api/refills/runs/{run_id}").json()
    assert {c["column_key"] for c in hist_again["columns"]} == {"A", "B", "C", "D"}


def test_runs_list_and_summary_by_run_id(client, seeded_location):
    first = client.post("/api/refills/run", params={"location_id": 1}).json()
    db = SessionLocal()
    lane = db.query(Lane).filter(Lane.slot_no == "A1").one()
    lane.stock = 20  # A1 补满
    db.commit()
    db.close()
    second = client.post("/api/refills/run", params={"location_id": 1}).json()

    runs = client.get("/api/refills/runs", params={"location_id": 1}).json()
    assert [r["id"] for r in runs] == [second["id"], first["id"]]

    # 指定历史 run_id 的汇总仍按快照
    s = client.get("/api/refills/summary", params={"location_id": 1, "run_id": first["id"]}).json()
    assert s["total_fill"] == 32
    s2 = client.get("/api/refills/summary", params={"location_id": 1, "run_id": second["id"]}).json()
    assert s2["total_fill"] == 32 - 15


def test_invalid_slot_aborts_and_persists_nothing(client, seeded_location):
    db = SessionLocal()
    db.add(Lane(location_id=1, slot_no="9坏", sku_name="坏货道",
                capacity=10, stock=0, in_transit=0))
    db.commit()
    db.close()

    before_runs = client.get("/api/refills/runs", params={"location_id": 1}).json()
    r = client.post("/api/refills/run", params={"location_id": 1})
    assert r.status_code == 400
    after_runs = client.get("/api/refills/runs", params={"location_id": 1}).json()
    # 失败前后批次集合一致：没有任何分册/批次单独落库
    assert before_runs == after_runs

    db = SessionLocal()
    try:
        assert db.query(RefillRun).count() == 0
        assert db.query(RefillOrder).count() == 0
    finally:
        db.close()


def test_full_endpoint_uses_run_snapshot(client, seeded_location):
    run = client.post("/api/refills/run", params={"location_id": 1}).json()
    full = client.get("/api/refills/full", params={"location_id": 1}).json()
    assert {l["slot_no"] for l in full["lanes"]} == {"A2", "B2", "D1"}
    assert full["run_id"] == run["id"]


def test_mid_persist_failure_rolls_back_half_written_booklets(client, seeded_location, monkeypatch):
    """落库环节中途失败：已 flush 的整机批次和前半套分册必须全部回滚。"""
    import app.api.refills as refills_mod
    from app.models.models import RefillOrder as _RO
    from app.database import SessionLocal

    db = SessionLocal()
    orig_add = type(db).add
    order_adds = {"n": 0}

    def sabotaged_add(self, instance):
        if isinstance(instance, _RO):
            order_adds["n"] += 1
            if order_adds["n"] == 2:  # B 册写入瞬间炸库
                raise RuntimeError("模拟落库中途磁盘故障")
        return orig_add(self, instance)

    monkeypatch.setattr(type(db), "add", sabotaged_add)
    import pytest
    with pytest.raises(RuntimeError):
        refills_mod._persist_run(db, 1)
    db.close()

    db2 = SessionLocal()
    try:
        assert db2.query(RefillRun).count() == 0
        assert db2.query(RefillOrder).count() == 0
    finally:
        db2.close()

    # 回滚后数据库仍可正常生成一套完整分册
    ok = client.post("/api/refills/run", params={"location_id": 1})
    assert ok.status_code == 200
    assert {c["column_key"] for c in ok.json()["columns"] if c["order_id"]} == {"A", "B", "C"}


def test_seed_produces_a_and_b_booklets(db_setup):
    """走真实 seed_if_empty：种子后至少能看到 A 与 B 两组分册。"""
    from fastapi.testclient import TestClient

    from app.database import SessionLocal
    from app.main import app
    from app.services.seed import seed_if_empty

    db = SessionLocal()
    try:
        seed_if_empty(db)
    finally:
        db.close()

    with TestClient(app) as c:
        data = c.post("/api/refills/run", params={"location_id": 1}).json()
        by_key = {col["column_key"]: col for col in data["columns"]}
        assert "A" in by_key and "B" in by_key

        # 逐行货道与字母一致
        for col in data["columns"]:
            if col["order_id"] is None:
                continue
            order = c.get(f"/api/refills/orders/{col['order_id']}").json()
            for line in order["lines"]:
                assert line["column_key"] == col["column_key"]
                assert line["slot_no"].startswith(col["column_key"])

        # 汇总相加无漏无重
        s = c.get("/api/refills/summary", params={"location_id": 1}).json()
        assert sum(col["total_fill"] for col in s["columns"]) == s["total_fill"]
        assert s["total_fill"] == data["total_fill"] > 0
