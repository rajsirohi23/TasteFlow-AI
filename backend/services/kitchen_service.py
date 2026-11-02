"""Kitchen workload model used by the Kitchen Coordination Agent.

This is a transparent ESTIMATE, not a measurement:
  queue_minutes = sum(prep_minutes x quantity of every active order) / stations
Prep minutes come from the dish (if set) or from editable category defaults in
config.py. The response always says it is an estimate and shows its inputs.
"""
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

import config
from models import MenuItem, Order, OrderItem

ACTIVE_STATUSES = ("pending", "preparing")


def prep_minutes_for(item: MenuItem) -> int:
    if item.prep_minutes:
        return item.prep_minutes
    return config.CATEGORY_PREP_MINUTES.get(item.category, config.DEFAULT_PREP_MINUTES)


def get_kitchen_load(db: Session, extra_lines: list[tuple[int, int]] | None = None) -> dict:
    """Workload now, optionally including a not-yet-placed cart (extra_lines)."""
    cutoff = datetime.utcnow() - timedelta(hours=config.STALE_ORDER_HOURS)
    stale_orders = db.query(Order).filter(Order.status.in_(ACTIVE_STATUSES), Order.created_at < cutoff).count()
    rows = (
        db.query(OrderItem, MenuItem, Order)
        .join(Order, Order.id == OrderItem.order_id)
        .join(MenuItem, MenuItem.id == OrderItem.menu_item_id)
        .filter(Order.status.in_(ACTIVE_STATUSES), Order.created_at >= cutoff)
        .all()
    )
    active_orders = {order.id for _, _, order in rows}
    now = datetime.utcnow()
    late_orders = len({o.id for _, _, o in rows
                       if (now - o.created_at).total_seconds() > (o.eta_minutes or config.DEFAULT_ETA_MINUTES) * 60})
    queue_work = sum(prep_minutes_for(menu) * oi.quantity for oi, menu, _ in rows)
    queue_items = sum(oi.quantity for oi, _, _ in rows)
    ready_count = db.query(Order).filter(Order.status == "ready").count()

    own_work = 0
    for item_id, qty in extra_lines or []:
        menu = db.get(MenuItem, item_id)
        if menu:
            own_work += prep_minutes_for(menu) * qty

    stations = max(config.KITCHEN_PARALLEL_STATIONS, 1)
    wait_before = round(queue_work / stations)
    estimated_ready = round((queue_work + own_work) / stations) if extra_lines else wait_before

    if wait_before >= config.KITCHEN_BUSY_WAIT_MINUTES:
        level = "busy"
    elif wait_before >= config.KITCHEN_MODERATE_WAIT_MINUTES:
        level = "moderate"
    else:
        level = "light"

    return {
        "level": level,
        "active_orders": len(active_orders),
        "late_orders": late_orders,
        "stale_orders": stale_orders,
        "items_in_queue": queue_items,
        "orders_ready_for_pickup": ready_count,
        "estimated_wait_minutes": wait_before,
        "estimated_ready_minutes": estimated_ready,
        "is_estimate": True,
        "basis": (f"{queue_work} prep-minutes queued across {stations} stations; "
                  "prep times are configured estimates"),
    }
