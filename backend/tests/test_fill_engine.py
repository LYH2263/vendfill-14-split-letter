import pytest

from app.services.fill_engine import (
    SplitError, build_fill_lines, compute_gap, lane_letter, plan_sheets,
    reconcile_split, summarize,
)

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

# ---- split by lane-code letter ----

def _lanes():
    return [
        {"id": 1, "slot_no": "A1", "sku_name": "水", "capacity": 10, "stock": 5, "in_transit": 0},
        {"id": 2, "slot_no": "A2", "sku_name": "可乐", "capacity": 10, "stock": 10, "in_transit": 0},
        {"id": 3, "slot_no": "B1", "sku_name": "薯片", "capacity": 8, "stock": 3, "in_transit": 0},
        {"id": 4, "slot_no": "C1", "sku_name": "饼干", "capacity": 6, "stock": 6, "in_transit": 0},
    ]

def test_lane_letter():
    assert lane_letter("A1") == "A"
    assert lane_letter("b12") == "B"
    assert lane_letter(" c3 ") == "C"
    assert lane_letter("") == "?"

def test_plan_sheets_groups_by_letter_and_keeps_zero_key():
    lines = build_fill_lines(_lanes())
    sheets, letters = plan_sheets(lines)
    # 字母台账覆盖所有字母，C 补量为 0 也不丢键
    assert letters == {"A": 5, "B": 5, "C": 0}
    # C 组无待补货道：不建空单
    assert [s.letter for s in sheets] == ["A", "B"]
    # 单上只含本组货道，且分册合计 = 行合计
    for s in sheets:
        assert all(lane_letter(l.slot_no) == s.letter for l in s.lines)
        assert s.total_fill == sum(l.fill_qty for l in s.lines)
    # 各分册之和 = 字母台账之和 = 整机总补件数
    machine_total = sum(l.fill_qty for l in lines)
    assert sum(s.total_fill for s in sheets) == machine_total
    assert sum(letters.values()) == machine_total

def test_reconcile_accepts_valid_plan():
    lines = build_fill_lines(_lanes())
    sheets, letters = plan_sheets(lines)
    reconcile_split(sheets, letters, lines)  # no raise

def test_reconcile_rejects_cross_letter_row():
    lines = build_fill_lines(_lanes())
    sheets, letters = plan_sheets(lines)
    a, b = sheets
    moved = a.lines.pop(0)  # A1 -> B 组单：串组
    b.lines.append(moved)
    a.total_fill -= moved.fill_qty
    b.total_fill += moved.fill_qty
    with pytest.raises(SplitError):
        reconcile_split(sheets, letters, lines)

def test_reconcile_rejects_missing_need_fill_lane():
    lines = build_fill_lines(_lanes())
    sheets, letters = plan_sheets(lines)
    dropped = sheets[0].lines.pop(0)  # 丢掉待补的 A1：漏行
    sheets[0].total_fill -= dropped.fill_qty
    with pytest.raises(SplitError):
        reconcile_split(sheets, letters, lines)

def test_reconcile_rejects_duplicate_lane():
    lines = build_fill_lines(_lanes())
    sheets, letters = plan_sheets(lines)
    dup = sheets[1].lines[0]
    sheets[1].lines.append(dup)  # 同一货道写两次：重行
    sheets[1].total_fill += dup.fill_qty
    with pytest.raises(SplitError):
        reconcile_split(sheets, letters, lines)

def test_reconcile_rejects_dropped_letter_key():
    lines = build_fill_lines(_lanes())
    sheets, letters = plan_sheets(lines)
    del letters["C"]  # silently 丢掉补量为 0 的字母键
    with pytest.raises(SplitError):
        reconcile_split(sheets, letters, lines)

def test_reconcile_rejects_empty_sheet_for_zero_letter():
    lines = build_fill_lines(_lanes())
    sheets, letters = plan_sheets(lines)
    from app.services.fill_engine import SheetPlan
    sheets.append(SheetPlan(letter="C", total_fill=0, lines=[]))  # 给 0 字母建空单
    with pytest.raises(SplitError):
        reconcile_split(sheets, letters, lines)

def test_reconcile_rejects_total_mismatch():
    lines = build_fill_lines(_lanes())
    sheets, letters = plan_sheets(lines)
    sheets[0].total_fill += 1  # 分册合计被篡改
    with pytest.raises(SplitError):
        reconcile_split(sheets, letters, lines)
