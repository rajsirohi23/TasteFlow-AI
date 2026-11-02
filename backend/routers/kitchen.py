from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from auth import require_role
from database import get_db
from models import Order
from order_schemas import OrderResponse, OrderStatusUpdate
from services.kitchen_service import get_kitchen_load
from datetime import datetime

import config
from models import MenuItem, OrderItem
from services.order_service import is_valid_status_transition, order_to_response, orders_to_responses, set_status

# Every kitchen route needs a kitchen (or owner) login.
router = APIRouter(
    prefix="/api/kitchen",
    tags=["Kitchen"],
    dependencies=[Depends(require_role("kitchen"))],
)


@router.get("/orders", response_model=list[OrderResponse])
def get_kitchen_orders(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    orders = (
        db.query(Order)
        .filter(Order.status.in_(["pending", "preparing", "ready"]))
        .order_by(Order.created_at.asc(), Order.id.asc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return orders_to_responses(db, orders)


@router.get("/load")
def kitchen_load(db: Session = Depends(get_db)):
    """Current workload and estimated wait (see services/kitchen_service.py)."""
    return get_kitchen_load(db)


@router.patch("/orders/{order_id}/status", response_model=OrderResponse)
def update_kitchen_order_status(
    order_id: int, status_data: OrderStatusUpdate, db: Session = Depends(get_db)
):
    order = db.get(Order, order_id)
    if order is None:
        raise HTTPException(status_code=404, detail=f"Order {order_id} was not found")
    if not is_valid_status_transition(order.status, status_data.status):
        raise HTTPException(
            status_code=409,
            detail=f"Cannot change order status from '{order.status}' to '{status_data.status}'.",
        )
    set_status(db, order, status_data.status)
    db.commit()
    db.refresh(order)
    return order_to_response(db, order)


@router.get("/board")
def kitchen_board(db: Session = Depends(get_db)):
    """Everything the kitchen display needs in one call: orders with dish names, timing and lateness."""
    orders = (db.query(Order).filter(Order.status.in_(["pending", "preparing", "ready"]))
              .order_by(Order.created_at.asc(), Order.id.asc()).all())
    names = dict(db.query(MenuItem.id, MenuItem.name).all())
    by_order: dict[int, list] = {}
    if orders:
        for oi in db.query(OrderItem).filter(OrderItem.order_id.in_([o.id for o in orders])).order_by(OrderItem.id).all():
            by_order.setdefault(oi.order_id, []).append({"name": names.get(oi.menu_item_id, "Item"), "quantity": oi.quantity})
    now = datetime.utcnow()
    cards = []
    for o in orders:
        eta = o.eta_minutes or config.DEFAULT_ETA_MINUTES
        elapsed = (now - o.created_at).total_seconds()
        cards.append({"id": o.id, "status": o.status, "customer_name": o.customer_name,
                      "order_type": o.order_type or "takeaway", "table_number": o.table_number, "notes": o.notes,
                      "items": by_order.get(o.id, []), "total_amount": o.total_amount, "source": o.source,
                      "placed_at": o.created_at.isoformat() + "Z", "eta_minutes": eta,
                      "elapsed_seconds": round(elapsed), "late": o.status in ("pending", "preparing") and elapsed > eta * 60,
                      "stale": o.status in ("pending", "preparing") and elapsed > config.STALE_ORDER_HOURS * 3600})
    return {"orders": cards, "load": get_kitchen_load(db), "server_time": now.isoformat() + "Z"}
