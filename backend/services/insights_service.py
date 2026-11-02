"""Restaurant Intelligence: business insights computed from REAL data.

Every sentence is produced by code from SQL results (never by an LLM), and each
insight carries its evidence numbers. When there is not enough data the service
says so instead of guessing.
"""
from collections import Counter, defaultdict

from sqlalchemy import func
from sqlalchemy.orm import Session

import config
from models import MenuItem, Order, OrderItem, UnmetDemand
from services.ops_service import feedback_summary, inventory_summary, operations_summary
from services.time_utils import to_local


def _pct(part: float, whole: float) -> int:
    return round(100 * part / whole) if whole else 0


def describe_filters(filters: dict | None) -> str:
    f = filters or {}
    parts = [f.get("diet"), (f.get("category") or "").lower() or None,
             f"under ₹{f['budget']}" if f.get("budget") is not None else None,
             f"spice up to {f['max_spice_level']}" if f.get("max_spice_level") else None,
             f"{f['spice_level']} spice" if f.get("spice_level") else None,
             "high-protein" if f.get("protein_focus") else None]
    return " ".join(p for p in parts if p) or "unspecified request"


def unmet_demand_summary(db: Session, limit: int = 10) -> list[dict]:
    rows = db.query(UnmetDemand).order_by(UnmetDemand.id.desc()).limit(500).all()
    groups: dict[str, dict] = {}
    for r in rows:
        key = describe_filters(r.filters)
        g = groups.setdefault(key, {"request": key, "count": 0, "examples": [], "last_seen": r.created_at})
        g["count"] += 1
        if len(g["examples"]) < 2 and r.query_text not in g["examples"]:
            g["examples"].append(r.query_text)
    return sorted(groups.values(), key=lambda g: -g["count"])[:limit]


def build_insights(db: Session) -> dict:
    base = db.query(Order).filter(Order.status != "cancelled")
    order_count = base.count()
    demo_count = base.filter(Order.is_demo.is_(True)).count()
    distinct_days = len({to_local(o.created_at).date() for o in base.all()})
    sufficient = order_count >= config.MIN_ORDERS_FOR_INSIGHTS
    insights: list[dict] = []

    unmet = unmet_demand_summary(db)
    if unmet:
        top = unmet[0]
        total = sum(g["count"] for g in unmet)
        insights.append({"type": "unmet_demand", "evidence": {"requests": total, "top": top},
                         "text": f"{total} guest request{'s' if total != 1 else ''} matched no available dish. "
                                 f"The most common was “{top['request']}” ({top['count']}×)."})

    if order_count:
        rows = (db.query(MenuItem.category, func.sum(OrderItem.quantity), func.sum(OrderItem.quantity * OrderItem.unit_price))
                .join(OrderItem, OrderItem.menu_item_id == MenuItem.id)
                .join(Order, Order.id == OrderItem.order_id)
                .filter(Order.status != "cancelled").group_by(MenuItem.category).all())
        total_value = sum(r[2] or 0 for r in rows)
        total_qty = sum(r[1] or 0 for r in rows)
        if rows and total_value:
            cat, qty, value = max(rows, key=lambda r: r[2] or 0)
            insights.append({"type": "category_share", "evidence": {"category": cat, "value": value, "total_value": total_value, "orders": order_count},
                             "text": f"{cat} accounted for {_pct(value, total_value)}% of recorded order value "
                                     f"({qty} of {total_qty} items, across {order_count} non-cancelled orders)."})

        top_dish = (db.query(MenuItem.name, func.sum(OrderItem.quantity).label("q"))
                    .join(OrderItem, OrderItem.menu_item_id == MenuItem.id)
                    .join(Order, Order.id == OrderItem.order_id).filter(Order.status != "cancelled")
                    .group_by(MenuItem.id).order_by(func.sum(OrderItem.quantity).desc(), MenuItem.id).first())
        if top_dish:
            insights.append({"type": "top_dish", "evidence": {"dish": top_dish[0], "quantity": int(top_dish[1])},
                             "text": f"{top_dish[0]} is the most ordered dish ({int(top_dish[1])} portions)."})

        hours = Counter(to_local(o.created_at).hour for o in base.all())
        if hours and sufficient:
            hour, n = hours.most_common(1)[0]
            insights.append({"type": "peak_hour", "evidence": {"hour": hour, "orders": n},
                             "text": f"Orders peak around {hour:02d}:00 local time ({n} of {order_count} orders)."})

    never = (db.query(MenuItem).filter(MenuItem.available.is_(True))
             .filter(~MenuItem.id.in_(db.query(OrderItem.menu_item_id).join(Order, Order.id == OrderItem.order_id)
                                      .filter(Order.status != "cancelled"))).all())
    if order_count and never:
        insights.append({"type": "never_ordered", "evidence": {"count": len(never), "examples": [m.name for m in never[:5]]},
                         "text": f"{len(never)} available dishes have never been ordered, for example {', '.join(m.name for m in never[:3])}."})

    forecast = {"available": False, "reason": f"Needs at least {config.MIN_ORDERS_FOR_INSIGHTS} orders over 7+ days; "
                                              f"currently {order_count} orders over {distinct_days} day(s)."}
    if sufficient and distinct_days >= 7:
        per_day: dict = defaultdict(int)
        for o in base.all():
            per_day[to_local(o.created_at).date()] += 1
        last7 = sorted(per_day)[-7:]
        avg = sum(per_day[d] for d in last7) / len(last7)
        forecast = {"available": True, "method": "7-day moving average (naive baseline)",
                    "expected_orders_per_day": round(avg, 1)}

    ops = operations_summary(db)
    fb = feedback_summary(db)
    inv = inventory_summary(db)
    if ops["avg_minutes_to_ready"] is not None:
        tail = f" {ops['on_time_rate_pct']}% were ready within their estimate." if ops["on_time_rate_pct"] is not None else ""
        insights.append({"type": "kitchen_speed", "evidence": ops,
                         "text": f"Measured from timestamps, orders took {ops['avg_minutes_to_ready']} min on average to be ready "
                                 f"({ops['samples']} orders).{tail}"})
    if fb["count"]:
        top = fb["top_complaints"][0] if fb["top_complaints"] else None
        extra = f" Most common complaint: {top['topic']} ({top['count']}×)." if top else ""
        insights.append({"type": "feedback", "evidence": {"average": fb["average"], "count": fb["count"]},
                         "text": f"Guests rate you {fb['average']}/5 on average ({fb['count']} ratings); "
                                 f"{fb['needs_follow_up']} need follow-up.{extra}"})
    if inv["low_stock"] or inv["sold_out"]:
        names = ", ".join(f"{m['name']} ({m['stock']})" for m in (inv["sold_out"] + inv["low_stock"])[:4])
        insights.append({"type": "inventory", "evidence": inv,
                         "text": f"Stock alert: {len(inv['sold_out'])} sold out, {len(inv['low_stock'])} running low: {names}."})
    if demo_count:
        insights.insert(0, {"type": "demo_data", "evidence": {"demo_orders": demo_count, "orders": order_count},
                            "text": f"{demo_count} of {order_count} orders are labelled DEMO data (generated by seed_demo.py), not real guests."})
    if not sufficient:
        insights.insert(0, {"type": "data_warning", "evidence": {"orders": order_count},
                            "text": f"Only {order_count} order(s) recorded, so trends below are indicative, not statistically reliable."})
    return {"data_sufficiency": {"orders": order_count, "demo_orders": demo_count, "days": distinct_days,
                                 "minimum": config.MIN_ORDERS_FOR_INSIGHTS, "sufficient": sufficient},
            "insights": insights, "unmet_demand": unmet, "forecast": forecast,
            "operations": ops, "feedback": fb, "inventory": inv}
