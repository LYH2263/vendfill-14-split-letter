from app.services.fill_engine import (
    SplitError,
    build_fill_lines,
    build_run_snapshot,
    column_key_of,
    compute_gap,
    split_lines_by_column,
    summarize,
)
import pytest


def test_gap_basic():
    assert compute_gap(20, 5, 0) == 15
    assert compute_gap(20, 10, 5) == 5


def test_no_negative_fill():
    lanes = [{"id": 1, "slot_no": "A1", "sku_name": "水", "capacity": 10, "stock": 12, "in_transit": 0}]
    lines = build_fill_lines(lanes)
    assert lines[0].fill_qty == 0
    assert lines[0].status == "overbooked"


def test_cap_by_gap():
    lanes = [{"id": 1, "slot_no": "A1", "sku_name": "水", "capacity": 20, "stock": 5, "in_transit": 0}]
    lines = build_fill_lines(lanes, requested={1: 100})
    assert lines[0].fill_qty == 15
    assert lines[0].gap == 15


def test_full_zero_fill():
    lanes = [{"id": 1, "slot_no": "A1", "sku_name": "水", "capacity": 10, "stock": 8, "in_transit": 2}]
    s = summarize(build_fill_lines(lanes))
    assert s["full_count"] == 1
    assert s["total_fill"] == 0


# ---------- 立柱字母拆单 ----------

def test_column_key_uppercases_and_rejects_bad_slot():
    assert column_key_of("a1") == "A"
    assert column_key_of(" B9 ") == "B"
    with pytest.raises(SplitError):
        column_key_of("12")
    with pytest.raises(SplitError):
        column_key_of("")


def _lane(lane_id, slot, cap=10, stock=0, transit=0):
    return {"id": lane_id, "slot_no": slot, "sku_name": slot,
            "capacity": cap, "stock": stock, "in_transit": transit}


def test_split_groups_by_initial_letter_only():
    lines = build_fill_lines([_lane(1, "A1"), _lane(2, "A9"), _lane(3, "B1")])
    grouped = split_lines_by_column(lines)
    assert list(grouped) == ["A", "B"]
    assert {l.lane_id for l in grouped["A"]} == {1, 2}
    assert {l.lane_id for l in grouped["B"]} == {3}


def test_build_run_snapshot_reconciles_totals():
    # A1 缺 15，B1 缺 7，A2 满仓，C1 超占
    lanes = [
        _lane(1, "A1", cap=20, stock=5),
        _lane(2, "A2", cap=18, stock=18),
        _lane(3, "B1", cap=12, stock=3, transit=2),
        _lane(4, "C1", cap=24, stock=24, transit=2),
    ]
    snap = build_run_snapshot(lanes)
    by_key = {c["column_key"]: c for c in snap["columns"]}

    # 每个字母一册视图，行只含本字母货道
    assert {l["slot_no"] for l in by_key["A"]["lines"]} == {"A1", "A2"}
    assert {l["slot_no"] for l in by_key["B"]["lines"]} == {"B1"}
    assert {l["slot_no"] for l in by_key["C"]["lines"]} == {"C1"}
    assert all(l["column_key"] == "A" for l in by_key["A"]["lines"])

    # 分册补量
    assert by_key["A"]["total_fill"] == 15
    assert by_key["B"]["total_fill"] == 7
    assert by_key["C"]["total_fill"] == 0

    # 各分册之和 == 整机
    assert sum(c["total_fill"] for c in snap["columns"]) == snap["total_fill"] == 22
    assert sum(c["need_fill_count"] for c in snap["columns"]) == snap["need_fill_count"] == 2
    assert sum(c["full_count"] for c in snap["columns"]) == snap["full_count"] == 1
    assert sum(c["overbooked_count"] for c in snap["columns"]) == snap["overbooked_count"] == 1

    # has_pending 决定是否建册
    assert by_key["A"]["has_pending"] is True
    assert by_key["B"]["has_pending"] is True
    assert by_key["C"]["has_pending"] is False

    # 整机行视图每行带 column_key 且与货道编号一致
    assert {l["lane_id"]: l["column_key"] for l in snap["lines"]} == {1: "A", 2: "A", 3: "B", 4: "C"}


def test_zero_fill_column_key_is_retained_not_dropped():
    lanes = [_lane(1, "A1", cap=10, stock=2), _lane(2, "Z9", cap=5, stock=5)]
    snap = build_run_snapshot(lanes)
    keys = [c["column_key"] for c in snap["columns"]]
    assert keys == ["A", "Z"]  # Z 补量 0，键仍在
    z = next(c for c in snap["columns"] if c["column_key"] == "Z")
    assert z["total_fill"] == 0 and z["has_pending"] is False


def test_invalid_slot_aborts_snapshot():
    # 非法编号导致整次拆单失败，调用方拿不到半套结果
    with pytest.raises(SplitError):
        build_run_snapshot([_lane(1, "A1"), _lane(2, "无字母")])
