import json
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.models import Lane, Location, RefillOrder, RefillSheet
from app.services.fill_engine import (
    SplitError, build_fill_lines, line_to_dict, plan_sheets, reconcile_split,
)
router = APIRouter(prefix="/refills", tags=["refills"])

def _lane_payloads(db: Session, location_id: int) -> list[dict]:
    lanes = db.scalars(select(Lane).where(Lane.location_id == location_id)
                       .order_by(Lane.slot_no)).all()
    return [{"id": l.id, "slot_no": l.slot_no, "sku_name": l.sku_name,
             "capacity": l.capacity, "stock": l.stock, "in_transit": l.in_transit}
            for l in lanes]

def _persist_batch(db: Session, location_id: int, lines, sheets, letter_totals) -> RefillOrder:
    """Write the batch header and every sheet in one flush; the caller commits.
    Any exception propagates so the caller rolls back — no half set of sheets
    may survive a failed split."""
    order = RefillOrder(
        location_id=location_id, created_at=datetime.utcnow(),
        total_fill=sum(l.fill_qty for l in lines),
        letters_json=json.dumps(letter_totals, ensure_ascii=False),
        lines_json=json.dumps([line_to_dict(l) for l in lines], ensure_ascii=False),
    )
    db.add(order)
    db.flush()  # assign order.id for the sheets
    for plan in sheets:
        db.add(RefillSheet(
            order_id=order.id, location_id=location_id, group_letter=plan.letter,
            total_fill=plan.total_fill, created_at=order.created_at,
            lines_json=json.dumps([line_to_dict(l) for l in plan.lines], ensure_ascii=False),
        ))
    db.flush()
    return order

def _order_sheets(db: Session, order_id: int) -> list[RefillSheet]:
    return db.scalars(select(RefillSheet).where(RefillSheet.order_id == order_id)
                      .order_by(RefillSheet.id)).all()

def _batch_payload(order: RefillOrder, sheet_rows: list[RefillSheet]) -> dict:
    """Response built from stored snapshots only — history is never re-derived."""
    lines = json.loads(order.lines_json)
    sheets = [
        {"id": s.id, "order_id": s.order_id, "letter": s.group_letter,
         "total_fill": s.total_fill, "created_at": s.created_at.isoformat(),
         "lines": json.loads(s.lines_json)}
        for s in sheet_rows
    ]
    return {
        "id": order.id, "location_id": order.location_id,
        "created_at": order.created_at.isoformat(),
        "total_fill": order.total_fill,
        "letters": json.loads(order.letters_json),
        "sheets": sheets,
        "sheets_total": sum(s["total_fill"] for s in sheets),
        "need_fill_count": sum(1 for l in lines if l["status"] == "need_fill"),
        "full_count": sum(1 for l in lines if l["status"] == "full"),
        "overbooked_count": sum(1 for l in lines if l["status"] == "overbooked"),
        "lines": lines,
    }

@router.post("/run")
def run_refill(location_id: int = 1, db: Session = Depends(get_db)):
    loc = db.get(Location, location_id)
    if not loc: raise HTTPException(404, "点位不存在")
    lines = build_fill_lines(_lane_payloads(db, location_id))
    sheets, letter_totals = plan_sheets(lines)
    try:
        reconcile_split(sheets, letter_totals, lines)  # 对不齐即废：落库前一票否决
        order = _persist_batch(db, location_id, lines, sheets, letter_totals)
        db.commit()
    except SplitError as e:
        db.rollback()
        raise HTTPException(500, f"拆单对账失败，整批作废：{e}")
    except Exception:
        db.rollback()  # 任一环节失败：半套分册全部回滚，不得单独落库
        raise HTTPException(500, "拆单落库失败，已回滚，未保留任何分册")
    return _batch_payload(order, _order_sheets(db, order.id))

@router.get("/latest")
def latest(location_id: int = 1, db: Session = Depends(get_db)):
    order = db.scalars(select(RefillOrder).where(RefillOrder.location_id == location_id)
                       .order_by(RefillOrder.id.desc())).first()
    if not order:
        return run_refill(location_id=location_id, db=db)
    return _batch_payload(order, _order_sheets(db, order.id))

@router.get("/sheets")
def list_sheets(location_id: int = 1, order_id: int | None = None, db: Session = Depends(get_db)):
    if order_id is None:
        order = db.scalars(select(RefillOrder).where(RefillOrder.location_id == location_id)
                           .order_by(RefillOrder.id.desc())).first()
        if not order:
            return []
        order_id = order.id
    rows = _order_sheets(db, order_id)
    return [{"id": s.id, "order_id": s.order_id, "location_id": s.location_id,
             "letter": s.group_letter, "total_fill": s.total_fill,
             "created_at": s.created_at.isoformat(),
             "line_count": len(json.loads(s.lines_json))} for s in rows]

@router.get("/sheets/{sheet_id}")
def get_sheet(sheet_id: int, db: Session = Depends(get_db)):
    """Open one historical sheet: stored letter + rows as written at generation
    time; a later lane rename never rewrites this attribution."""
    s = db.get(RefillSheet, sheet_id)
    if not s: raise HTTPException(404, "分册不存在")
    return {"id": s.id, "order_id": s.order_id, "location_id": s.location_id,
            "letter": s.group_letter, "total_fill": s.total_fill,
            "created_at": s.created_at.isoformat(), "lines": json.loads(s.lines_json)}

@router.get("/full")
def full_lanes(location_id: int = 1, db: Session = Depends(get_db)):
    data = latest(location_id=location_id, db=db)
    return {"location_id": location_id, "lanes": [l for l in data["lines"] if l["status"] == "full"]}

@router.get("/summary")
def refill_summary(location_id: int = 1, db: Session = Depends(get_db)):
    """Per-location ledger: every letter key (0 included), every sheet total, and
    the balance check sheets_total == letters_total == total_fill."""
    data = latest(location_id=location_id, db=db)
    letters_total = sum(data["letters"].values())
    balanced = data["sheets_total"] == data["total_fill"] == letters_total
    return {
        "location_id": location_id,
        "order_id": data["id"],
        "created_at": data["created_at"],
        "total_fill": data["total_fill"],
        "letters": data["letters"],
        "letters_total": letters_total,
        "sheets": [{"id": s["id"], "letter": s["letter"], "total_fill": s["total_fill"],
                    "line_count": len(s["lines"])} for s in data["sheets"]],
        "sheets_total": data["sheets_total"],
        "balanced": balanced,
        "need_fill_count": data["need_fill_count"],
        "full_count": data["full_count"],
        "overbooked_count": data["overbooked_count"],
    }
