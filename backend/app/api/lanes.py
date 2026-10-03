from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.models import Lane
from app.services.fill_engine import compute_gap
router = APIRouter(prefix="/lanes", tags=["lanes"])

def _lane_dict(r: Lane) -> dict:
    gap = compute_gap(r.capacity, r.stock, r.in_transit)
    return {"id": r.id, "location_id": r.location_id, "slot_no": r.slot_no, "sku_name": r.sku_name,
            "capacity": r.capacity, "stock": r.stock, "in_transit": r.in_transit, "gap": gap,
            "fill_pct": round(r.stock / r.capacity * 100, 1) if r.capacity else 0}

@router.get("")
def list_lanes(location_id: int | None = None, db: Session = Depends(get_db)):
    q = select(Lane).order_by(Lane.slot_no)
    if location_id is not None: q = q.where(Lane.location_id == location_id)
    return [_lane_dict(r) for r in db.scalars(q).all()]

class LaneUpdate(BaseModel):
    slot_no: str | None = None
    sku_name: str | None = None
    capacity: int | None = None
    stock: int | None = None
    in_transit: int | None = None

@router.patch("/{lane_id}")
def update_lane(lane_id: int, body: LaneUpdate, db: Session = Depends(get_db)):
    """Edit a lane, e.g. rename its code. Historical refill sheets keep the
    letter/attribution frozen at their generation time and are not rewritten."""
    lane = db.get(Lane, lane_id)
    if not lane: raise HTTPException(404, "货道不存在")
    data = body.model_dump(exclude_unset=True)
    if "slot_no" in data:
        slot = (data["slot_no"] or "").strip()
        if not slot: raise HTTPException(422, "货道编号不能为空")
        data["slot_no"] = slot
    for k, v in data.items():
        setattr(lane, k, v)
    db.commit(); db.refresh(lane)
    return _lane_dict(lane)
