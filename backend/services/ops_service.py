"""Operations, feedback and inventory summaries for the owner (all from real rows)."""
from statistics import median

from sqlalchemy import func
from sqlalchemy.orm import Session

import config
from models import Feedback, MenuItem, Order, OrderStatusEvent


def operations_summary(db: Session) -> dict:
    """Measured kitchen speed from status timestamps (placed -> ready)."""
    ready = {}
    for e in db.query(OrderStatusEvent).filter(OrderStatusEvent.status == "ready").all():
        ready.setdefault(e.order_id, e.created_at)
    orders = {o.id: o for o in db.query(Order).filter(Order.id.in_(list(ready) or [0]), Order.status != "cancelled").all()}
    minutes, on_time = [], 0
    for oid, t in ready.items():
        o = orders.get(oid)
        if not o:
            continue
        m = (t - o.created_at).total_seconds() / 60
        minutes.append(m)
        if o.eta_minutes and m <= o.eta_minutes:
            on_time += 1
    with_eta = sum(1 for oid in ready if orders.get(oid) and orders[oid].eta_minutes)
    n = len(minutes)
    return {
        "samples": n,
        "avg_minutes_to_ready": round(sum(minutes) / n, 1) if n else None,
        "median_minutes_to_ready": round(median(minutes), 1) if n else None,
        "on_time_rate_pct": round(100 * on_time / with_eta) if with_eta else None,
        "sufficient": n >= 5,
    }


def feedback_summary(db: Session, recent: int = 8) -> dict:
    rows = db.query(Feedback).order_by(Feedback.id.desc()).all()
    n = len(rows)
    dist = {str(i): 0 for i in range(1, 6)}
    topics: dict[str, int] = {}
    for r in rows:
        dist[str(r.rating)] += 1
        for t in (r.topics or []):
            if t != "praise":
                topics[t] = topics.get(t, 0) + 1
    open_flags = [r for r in rows if not r.resolved]
    return {
        "count": n,
        "average": round(sum(r.rating for r in rows) / n, 2) if n else None,
        "distribution": dist,
        "top_complaints": sorted(({"topic": k, "count": v} for k, v in topics.items()), key=lambda x: -x["count"])[:5],
        "needs_follow_up": len(open_flags),
        "recent": [{"id": r.id, "order_id": r.order_id, "rating": r.rating, "comment": r.comment,
                    "topics": r.topics or [], "resolved": r.resolved,
                    "created_at": r.created_at.isoformat() + "Z"} for r in rows[:recent]],
    }


def inventory_summary(db: Session) -> dict:
    tracked = db.query(MenuItem).filter(MenuItem.stock_quantity.isnot(None)).order_by(MenuItem.stock_quantity, MenuItem.id).all()
    untracked = db.query(func.count(MenuItem.id)).filter(MenuItem.stock_quantity.is_(None)).scalar()
    low = [m for m in tracked if 0 < m.stock_quantity <= config.LOW_STOCK_THRESHOLD]
    out = [m for m in tracked if m.stock_quantity <= 0]
    fmt = lambda m: {"id": m.id, "name": m.name, "stock": m.stock_quantity}
    return {"tracked": len(tracked), "untracked": untracked, "threshold": config.LOW_STOCK_THRESHOLD,
            "low_stock": [fmt(m) for m in low], "sold_out": [fmt(m) for m in out]}
