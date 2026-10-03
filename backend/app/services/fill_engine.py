"""Vending refill: gap = capacity - stock - in_transit; fills capped by gap; no negative fills.

按货道编号（slot_no）首字母（立柱字母）拆单：
- 一次整机构建一个 RefillRun 快照，每个有待补货道的字母落一册 RefillOrder；
- 分册行只许含本字母货道，串组即失败；
- 各分册补量之和必须等于整机总补量，对不齐即失败（SplitError），调用方须整批回滚。
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass

_COLUMN_RE = re.compile(r"^\s*([A-Za-z])")


class SplitError(ValueError):
    """拆单或对账失败：非法货道编号、串组、分册与整机汇总对不上账。"""


@dataclass
class FillLine:
    lane_id: int
    slot_no: str
    sku_name: str
    capacity: int
    stock: int
    in_transit: int
    gap: int
    fill_qty: int
    status: str  # need_fill | full | overbooked


def compute_gap(capacity: int, stock: int, in_transit: int) -> int:
    return capacity - stock - in_transit


def column_key_of(slot_no: str) -> str:
    """货道编号所属立柱字母：取首字母并大写。非字母开头无法拆单，直接失败。"""
    m = _COLUMN_RE.match(slot_no or "")
    if not m:
        raise SplitError(f"货道编号缺少立柱字母前缀，无法拆单: {slot_no!r}")
    return m.group(1).upper()


def build_fill_lines(lanes: list[dict], requested: dict[int, int] | None = None) -> list[FillLine]:
    """requested optional desired fill per lane_id; capped by gap; never negative."""
    lines: list[FillLine] = []
    for lane in lanes:
        gap = compute_gap(int(lane["capacity"]), int(lane["stock"]), int(lane["in_transit"]))
        if gap < 0:
            status = "overbooked"
            fill = 0
        elif gap == 0:
            status = "full"
            fill = 0
        else:
            status = "need_fill"
            desire = gap if requested is None else int(requested.get(lane["id"], gap))
            fill = max(0, min(desire, gap))
        lines.append(FillLine(
            lane_id=lane["id"], slot_no=lane["slot_no"], sku_name=lane["sku_name"],
            capacity=lane["capacity"], stock=lane["stock"], in_transit=lane["in_transit"],
            gap=gap, fill_qty=fill, status=status,
        ))
    return lines


def summarize(lines: list[FillLine]) -> dict:
    return {
        "total_fill": sum(l.fill_qty for l in lines),
        "need_fill_count": sum(1 for l in lines if l.status == "need_fill"),
        "full_count": sum(1 for l in lines if l.status == "full"),
        "overbooked_count": sum(1 for l in lines if l.status == "overbooked"),
        "lines": [asdict(l) for l in lines],
    }


def split_lines_by_column(lines: list[FillLine]) -> dict[str, list[FillLine]]:
    """按立柱字母分组。非法编号抛 SplitError；同一字母保持输入顺序，字母键排序返回。"""
    grouped: dict[str, list[FillLine]] = {}
    for line in lines:
        key = column_key_of(line.slot_no)
        grouped.setdefault(key, []).append(line)
    return {key: grouped[key] for key in sorted(grouped)}


def _line_to_dict(line: FillLine, column_key: str) -> dict:
    row = asdict(line)
    row["column_key"] = column_key
    return row


def _verify_reconciliation(overall: dict, column_rows: list[dict], all_line_dicts: list[dict]) -> None:
    """分册 ↔ 整机对账。任何一处对不上即抛 SplitError，调用方不得落库任何分册。"""
    # 1) 行守恒：每个货道行恰好属于一册，不得漏行/重行/串组。
    if sum(len(c["lines"]) for c in column_rows) != len(all_line_dicts):
        raise SplitError("拆单行数与整机行数不一致（漏行或重行），整单作废")
    for c in column_rows:
        for row in c["lines"]:
            if row["column_key"] != c["column_key"]:
                raise SplitError(
                    f"立柱 {c['column_key']} 分册混入货道 {row['slot_no']}（串组），整单作废"
                )
    seen: set[int] = set()
    for c in column_rows:
        for row in c["lines"]:
            if row["lane_id"] in seen:
                raise SplitError(f"货道 {row['slot_no']} 被重复归入多个分册，整单作废")
            seen.add(row["lane_id"])
    if seen != {row["lane_id"] for row in all_line_dicts}:
        raise SplitError("分册货道集合与整机货道集合不一致，整单作废")

    # 2) 数量守恒：各分册之和必须逐字段等于整机汇总。
    if sum(c["total_fill"] for c in column_rows) != overall["total_fill"]:
        raise SplitError("各分册补件数之和不等于整机总补件数，整单作废")
    for field in ("need_fill_count", "full_count", "overbooked_count"):
        if sum(c[field] for c in column_rows) != overall[field]:
            raise SplitError(f"各分册 {field} 之和与整机不一致，整单作废")


def build_run_snapshot(lanes: list[dict], requested: dict[int, int] | None = None) -> dict:
    """构建一次整机补货的完整快照（不写库）。

    返回:
      {
        整机汇总四计数,
        "lines": 全部货道行（每行带 column_key）,
        "columns": [ 每个出现过的立柱字母一条，补量可为 0，字母键不丢
          {column_key, total_fill, need_fill_count, full_count, overbooked_count,
           has_pending: 是否有待补货道（False 则允许不建空单）, lines: 该字母全部行}
        ],
      }
    """
    lines = build_fill_lines(lanes, requested)
    grouped = split_lines_by_column(lines)  # 非法编号在此失败

    all_line_dicts: list[dict] = []
    column_rows: list[dict] = []
    for key, group in grouped.items():
        row_dicts = [_line_to_dict(l, key) for l in group]
        all_line_dicts.extend(row_dicts)
        column_rows.append({
            "column_key": key,
            "total_fill": sum(r["fill_qty"] for r in row_dicts),
            "need_fill_count": sum(1 for r in row_dicts if r["status"] == "need_fill"),
            "full_count": sum(1 for r in row_dicts if r["status"] == "full"),
            "overbooked_count": sum(1 for r in row_dicts if r["status"] == "overbooked"),
            "has_pending": any(r["status"] == "need_fill" for r in row_dicts),
            "lines": row_dicts,
        })

    overall = summarize(lines)
    overall["lines"] = all_line_dicts
    _verify_reconciliation(overall, column_rows, all_line_dicts)
    overall["columns"] = column_rows
    return overall
