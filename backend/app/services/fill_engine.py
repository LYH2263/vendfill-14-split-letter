"""Vending refill: gap = capacity - stock - in_transit; fills capped by gap; no negative fills.

Splitting: one run groups fill lines by the lane code's leading letter; each letter
with something to fill becomes one sheet (分册); letters with nothing to fill get no
sheet but stay visible in the letter ledger. reconcile_split() enforces the books:
any miss, duplicate, cross-letter row or total mismatch voids the whole run.
"""
from __future__ import annotations
from dataclasses import asdict, dataclass

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

@dataclass
class SheetPlan:
    """One letter group's sheet before persistence."""
    letter: str
    total_fill: int
    lines: list[FillLine]

class SplitError(ValueError):
    """Raised when the split books do not balance; the run must be voided."""

def compute_gap(capacity: int, stock: int, in_transit: int) -> int:
    return capacity - stock - in_transit

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

def lane_letter(slot_no: str) -> str:
    """Grouping key: first character of the lane code, uppercased ('b1' -> 'B')."""
    code = (slot_no or "").strip()
    return code[0].upper() if code else "?"

def line_to_dict(line: FillLine) -> dict:
    """Snapshot dict for one line; the letter is frozen at generation time so
    historical sheets keep their original attribution even if the lane is renamed."""
    d = asdict(line)
    d["letter"] = lane_letter(line.slot_no)
    return d

def plan_sheets(lines: list[FillLine]) -> tuple[list[SheetPlan], dict[str, int]]:
    """Group fill lines by lane-code letter.

    Returns (sheets, letter_totals):
    - sheets: one SheetPlan per letter that has anything to fill (no empty sheets);
      each sheet holds exactly the lines of its own letter.
    - letter_totals: every letter present in the run, including letters whose
      total is 0 — the ledger never silently drops a letter key.
    """
    groups: dict[str, list[FillLine]] = {}
    for line in lines:
        groups.setdefault(lane_letter(line.slot_no), []).append(line)
    letter_totals = {
        letter: sum(l.fill_qty for l in group)
        for letter, group in sorted(groups.items())
    }
    sheets = [
        SheetPlan(letter=letter, total_fill=total, lines=groups[letter])
        for letter, total in letter_totals.items() if total > 0
    ]
    return sheets, letter_totals

def reconcile_split(sheets: list[SheetPlan], letter_totals: dict[str, int],
                    lines: list[FillLine]) -> None:
    """Void the run unless sheets, letter ledger and machine lines agree exactly.

    Checks: sheet totals add up to the machine total; the letter ledger adds up to
    the machine total; every sheet row belongs to its sheet's letter; no lane is
    written into two sheets; no lane needing fill is missing from every sheet;
    sheets exist exactly for the letters with a non-zero total.
    """
    problems: list[str] = []
    machine_total = sum(l.fill_qty for l in lines)
    machine_letters = {lane_letter(l.slot_no) for l in lines}
    if set(letter_totals.keys()) != machine_letters:
        problems.append("字母台账键与整机货道字母不一致(字母键不得丢失)")
    if sum(letter_totals.values()) != machine_total:
        problems.append("字母台账之和 != 整机总补件数")
    if sum(s.total_fill for s in sheets) != machine_total:
        problems.append("各分册之和 != 整机总补件数")
    if {s.letter for s in sheets} != {k for k, v in letter_totals.items() if v > 0}:
        problems.append("分册字母集合与待补字母集合不一致")
    seen: dict[int, str] = {}
    for sheet in sheets:
        if sheet.total_fill != sum(l.fill_qty for l in sheet.lines):
            problems.append(f"分册 {sheet.letter} 合计与其行不符")
        for line in sheet.lines:
            if lane_letter(line.slot_no) != sheet.letter:
                problems.append(f"货道 {line.slot_no} 串组写入分册 {sheet.letter}")
            if line.lane_id in seen:
                problems.append(f"货道 {line.slot_no} 重复落单({seen[line.lane_id]}/{sheet.letter})")
            seen[line.lane_id] = sheet.letter
    for line in lines:
        if line.fill_qty > 0 and line.lane_id not in seen:
            problems.append(f"待补货道 {line.slot_no} 未落入任何分册")
    if problems:
        raise SplitError("; ".join(problems))

def summarize(lines: list[FillLine]) -> dict:
    return {
        "total_fill": sum(l.fill_qty for l in lines),
        "need_fill_count": sum(1 for l in lines if l.status == "need_fill"),
        "full_count": sum(1 for l in lines if l.status == "full"),
        "overbooked_count": sum(1 for l in lines if l.status == "overbooked"),
        "lines": [asdict(l) for l in lines],
    }
