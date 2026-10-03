import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.models import Lane, Location, RefillOrder, RefillRun
from app.services.fill_engine import SplitError, build_run_snapshot

router = APIRouter(prefix="/refills", tags=["refills"])


def _lanes_payload(db: Session, location_id: int) -> list[dict]:
    lanes = db.scalars(
        select(Lane).where(Lane.location_id == location_id).order_by(Lane.slot_no)
    ).all()
    return [
        {"id": l.id, "slot_no": l.slot_no, "sku_name": l.sku_name,
         "capacity": l.capacity, "stock": l.stock, "in_transit": l.in_transit}
        for l in lanes
    ]


def _persist_run(db: Session, location_id: int) -> RefillRun:
    """构建快照并把整机批次 + 各字母分册一次事务落库。

    快照构建阶段失败（非法编号/串组/对账不平）不写任何数据；
    落库阶段任一环节失败一律 rollback，已写入的半套分册不得残留。
    """
    snapshot = build_run_snapshot(_lanes_payload(db, location_id))

    run = RefillRun(
        location_id=location_id,
        created_at=datetime.utcnow(),
        total_fill=snapshot["total_fill"],
        need_fill_count=snapshot["need_fill_count"],
        full_count=snapshot["full_count"],
        overbooked_count=snapshot["overbooked_count"],
        lines_json=json.dumps(snapshot["lines"], ensure_ascii=False),
        columns_json=json.dumps(
            [{k: c[k] for k in
              ("column_key", "total_fill", "need_fill_count",
               "full_count", "overbooked_count", "has_pending")}
             for c in snapshot["columns"]],
            ensure_ascii=False,
        ),
    )
    db.add(run)
    db.flush()  # 取得 run.id；失败则本事务内尚无分册

    try:
        created_keys: set[str] = set()
        for col in snapshot["columns"]:
            if not col["has_pending"]:
                continue  # 无待补货道：允许不建空单，字母键仍留在 run.columns_json
            if col["column_key"] in created_keys:
                raise SplitError(f"立柱 {col['column_key']} 分册重复，整单作废")
            created_keys.add(col["column_key"])
            order = RefillOrder(
                run_id=run.id,
                location_id=location_id,
                column_key=col["column_key"],
                total_fill=col["total_fill"],
                created_at=run.created_at,
                lines_json=json.dumps(col["lines"], ensure_ascii=False),
            )
            db.add(order)
        db.flush()

        # 落库后再对一次账：各分册补量之和必须等于整机总补件数。
        persisted = db.scalars(
            select(RefillOrder).where(RefillOrder.run_id == run.id)
        ).all()
        if sum(o.total_fill for o in persisted) != run.total_fill:
            raise SplitError("落库分册补量之和与整机总补件数不一致，整单作废")
        if sorted(o.column_key for o in persisted) != sorted(created_keys):
            raise SplitError("落库分册字母集合与拆单结果不一致，整单作废")

        db.commit()
    except Exception:
        db.rollback()  # 整机批次与半套分册一并回滚
        raise
    db.refresh(run)
    return run


def _serialize_run(run: RefillRun, orders: list[RefillOrder] | None = None) -> dict:
    """组装批次响应。分册内容只读取落库快照，绝不用当前货道数据现算。"""
    if orders is None:
        orders = []
    orders_by_key = {o.column_key: o for o in orders}
    columns = json.loads(run.columns_json)
    for col in columns:
        order = orders_by_key.get(col["column_key"])
        col["order_id"] = order.id if order else None
        # 历史分册行来自分册自身的快照；未建空单的字母行列表为空（补量已标 0）。
        col["lines"] = json.loads(order.lines_json) if order else []
    return {
        "id": run.id,
        "location_id": run.location_id,
        "created_at": run.created_at.isoformat(),
        "total_fill": run.total_fill,
        "need_fill_count": run.need_fill_count,
        "full_count": run.full_count,
        "overbooked_count": run.overbooked_count,
        "columns": columns,
        "lines": json.loads(run.lines_json),
    }


def _get_location(db: Session, location_id: int) -> Location:
    loc = db.get(Location, location_id)
    if not loc:
        raise HTTPException(404, "点位不存在")
    return loc


def _load_run(db: Session, run_id: int) -> RefillRun:
    run = db.get(RefillRun, run_id)
    if not run:
        raise HTTPException(404, "补货批次不存在")
    return run


@router.post("/run")
def run_refill(location_id: int = 1, db: Session = Depends(get_db)):
    _get_location(db, location_id)
    try:
        run = _persist_run(db, location_id)
    except SplitError as exc:
        raise HTTPException(400, f"拆单失败，未生成任何分册：{exc}")
    orders = db.scalars(select(RefillOrder).where(RefillOrder.run_id == run.id)).all()
    return _serialize_run(run, orders)


@router.get("/runs")
def list_runs(location_id: int = 1, db: Session = Depends(get_db)):
    """历史批次列表（不含行明细）。"""
    runs = db.scalars(
        select(RefillRun)
        .where(RefillRun.location_id == location_id)
        .order_by(RefillRun.id.desc())
    ).all()
    return [
        {
            "id": r.id,
            "location_id": r.location_id,
            "created_at": r.created_at.isoformat(),
            "total_fill": r.total_fill,
            "need_fill_count": r.need_fill_count,
            "full_count": r.full_count,
            "overbooked_count": r.overbooked_count,
            "column_count": len(json.loads(r.columns_json)),
        }
        for r in runs
    ]


@router.get("/runs/{run_id}")
def get_run(run_id: int, db: Session = Depends(get_db)):
    """打开历史批次：归属与行内容全部读快照，货道编号事后被改也不会改口。"""
    run = _load_run(db, run_id)
    orders = db.scalars(select(RefillOrder).where(RefillOrder.run_id == run.id)).all()
    return _serialize_run(run, orders)


@router.get("/orders/{order_id}")
def get_order(order_id: int, db: Session = Depends(get_db)):
    """打开单张历史分册，内容只认落库快照。"""
    order = db.get(RefillOrder, order_id)
    if not order:
        raise HTTPException(404, "补货分册不存在")
    return {
        "id": order.id,
        "run_id": order.run_id,
        "location_id": order.location_id,
        "column_key": order.column_key,
        "total_fill": order.total_fill,
        "created_at": order.created_at.isoformat(),
        "lines": json.loads(order.lines_json),
    }


@router.get("/latest")
def latest(location_id: int = 1, db: Session = Depends(get_db)):
    _get_location(db, location_id)
    run = db.scalars(
        select(RefillRun)
        .where(RefillRun.location_id == location_id)
        .order_by(RefillRun.id.desc())
    ).first()
    if run is None:
        try:
            run = _persist_run(db, location_id)
        except SplitError as exc:
            raise HTTPException(400, f"拆单失败，未生成任何分册：{exc}")
    orders = db.scalars(select(RefillOrder).where(RefillOrder.run_id == run.id)).all()
    return _serialize_run(run, orders)


@router.get("/full")
def full_lanes(location_id: int = 1, run_id: int | None = None, db: Session = Depends(get_db)):
    """满仓货道取批次快照（默认最新批次），不按当前货道现算。"""
    if run_id is not None:
        run = _load_run(db, run_id)
    else:
        data = latest(location_id=location_id, db=db)
        return {"location_id": location_id, "run_id": data["id"],
                "lanes": [l for l in data["lines"] if l["status"] == "full"]}
    return {"location_id": run.location_id, "run_id": run.id,
            "lanes": [l for l in json.loads(run.lines_json) if l["status"] == "full"]}


@router.get("/summary")
def refill_summary(location_id: int = 1, run_id: int | None = None, db: Session = Depends(get_db)):
    """整机汇总 + 各立柱字母分册补量。

    columns 保留该次拆单出现过的全部字母键：未建空单的字母 total_fill=0、
    order_id=null，不静默丢键；各分册 total_fill 之和恒等于整机 total_fill。
    """
    if run_id is not None:
        run = _load_run(db, run_id)
        orders = db.scalars(select(RefillOrder).where(RefillOrder.run_id == run.id)).all()
        data = _serialize_run(run, orders)
    else:
        data = latest(location_id=location_id, db=db)
    return {
        "location_id": data["location_id"],
        "run_id": data["id"],
        "created_at": data["created_at"],
        "total_fill": data["total_fill"],
        "need_fill_count": data["need_fill_count"],
        "full_count": data["full_count"],
        "overbooked_count": data["overbooked_count"],
        "columns": [
            {k: c[k] for k in
             ("column_key", "order_id", "total_fill", "need_fill_count",
              "full_count", "overbooked_count", "has_pending")}
            for c in data["columns"]
        ],
    }
