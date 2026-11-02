"""Order tracking: the numbers behind "your order will be ready in N minutes".

Everything is computed from the order's real timestamps. The ETA is the
kitchen agent's estimate made when the order was placed; if the kitchen runs
over it, the order is reported as delayed instead of showing a fake countdown.
"""
import math
from datetime import datetime

from sqlalchemy.orm import Session

import config
from models import Feedback, MenuItem, Order, OrderItem, OrderStatusEvent

STEP_LABELS = [("pending", "Order placed"), ("preparing", "Being prepared"),
               ("ready", "Ready for pickup"), ("completed", "Completed")]
ACTIVE = ("pending", "preparing")


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() + "Z" if dt else None


def find_by_code(db: Session, code: str) -> Order | None:
    code = (code or "").strip().upper()
    if not code or len(code) > 12:
        return None
    return db.query(Order).filter(Order.tracking_code == code).first()


def get_tracking(db: Session, order: Order) -> dict:
    now = datetime.utcnow()
    events = db.query(OrderStatusEvent).filter(OrderStatusEvent.order_id == order.id).order_by(OrderStatusEvent.id).all()
    at: dict[str, datetime] = {}
    for e in events:
        at.setdefault(e.status, e.created_at)
    at.setdefault("pending", order.created_at)

    eta = order.eta_minutes or config.DEFAULT_ETA_MINUTES
    status = order.status
    end = at.get("ready") or at.get("completed") if status in ("ready", "completed") else None
    if status == "cancelled":
        end = at.get("cancelled")
    elapsed = ((end or now) - order.created_at).total_seconds()
    remaining = max(0, eta * 60 - elapsed) if status in ACTIVE else None
    delay_min = math.ceil((elapsed - eta * 60) / 60) if status in ACTIVE and elapsed > eta * 60 else 0

    ahead = 0
    if status == "pending":
        ahead = db.query(Order).filter(Order.status.in_(ACTIVE), Order.created_at < order.created_at,
                                       Order.id != order.id).count()

    if status == "cancelled":
        state, message = "cancelled", "This order was cancelled."
    elif status == "completed":
        state, message = "completed", "Enjoy your meal! This order is complete."
    elif status == "ready":
        took = round(elapsed / 60)
        state, message = "ready", "Your order is ready for pickup." + (f" It took about {took} min." if took >= 1 else "")
    elif status in ACTIVE and elapsed > config.STALE_ORDER_HOURS * 3600:
        state, message = "delayed", "This order looks abandoned. Please ask the restaurant staff about it."
    elif delay_min > 0:
        state = "delayed"
        message = f"Taking longer than the {eta}-minute estimate (about {delay_min} min over). The kitchen is still working on it."
    elif status == "preparing":
        state, message = "on_time", f"Being prepared now. About {math.ceil(remaining / 60)} min to go (an estimate)."
    else:
        extra = f" {ahead} order{'s' if ahead != 1 else ''} ahead of yours." if ahead else ""
        state, message = "on_time", f"Order received.{extra} About {math.ceil(remaining / 60)} min to go (an estimate)."

    steps = []
    reached = [s for s, _ in STEP_LABELS if s in at or s == status]
    for key, label in STEP_LABELS:
        steps.append({"key": key, "label": label, "at": _iso(at.get(key)),
                      "done": key in at, "current": key == status})
    names = dict(db.query(MenuItem.id, MenuItem.name).all())
    items = [{"name": names.get(oi.menu_item_id, "Item"), "quantity": oi.quantity}
             for oi in db.query(OrderItem).filter(OrderItem.order_id == order.id).order_by(OrderItem.id).all()]
    rated = db.query(Feedback.id).filter(Feedback.order_id == order.id).first() is not None
    return {
        "code": order.tracking_code, "order_id": order.id, "status": status, "state": state, "message": message,
        "customer_first_name": order.customer_name.split()[0], "order_type": order.order_type or "takeaway",
        "table_number": order.table_number, "notes": order.notes, "items": items, "total_amount": order.total_amount,
        "placed_at": _iso(order.created_at), "eta_minutes": eta, "is_estimate": True,
        "elapsed_seconds": round(elapsed), "remaining_seconds": round(remaining) if remaining is not None else None,
        "delay_minutes": delay_min, "orders_ahead": ahead, "steps": steps, "reached": reached,
        "can_cancel": status == "pending", "can_rate": status in ("ready", "completed") and not rated,
        "rated": rated, "server_time": _iso(now),
    }
