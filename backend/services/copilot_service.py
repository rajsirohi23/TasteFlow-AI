"""Business Copilot: answers the owner's plain-language questions from real data.

It does NOT let a language model write SQL. Questions are mapped to a fixed set of
audited analytics functions, so every answer is reproducible and shows its basis."""
import re
from collections import Counter
from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from agents.nlu import match_dish_names
from models import Feedback, MenuItem, Order, OrderItem
from services.command_service import DAYS, day_bounds, inr, valid_orders
from services.ops_service import inventory_summary, operations_summary
from services.time_utils import local_now, to_local

HELP = ("Try: “revenue this week vs last week”, “top dishes yesterday”, “how many orders today”, "
        "“busiest hour”, “average order value”, “which dishes never sell”, “ratings this month”, "
        "“how many paneer tikka last week”, “what did guests ask for that we don't have?”.")


def resolve_period(text: str, today: date) -> tuple[datetime, datetime, str]:
    mon = today - timedelta(days=today.weekday())
    if "yesterday" in text:
        y = today - timedelta(days=1)
        return (*day_bounds(y), "yesterday")
    if re.search(r"\btoday\b|\bso far\b|\bright now\b", text):
        return (*day_bounds(today), "today")
    if "last week" in text:
        return day_bounds(mon - timedelta(days=7))[0], day_bounds(mon)[0], "last week (Mon–Sun)"
    if "this week" in text:
        return day_bounds(mon)[0], day_bounds(today)[1], "this week (since Monday)"
    if re.search(r"this month", text):
        return day_bounds(today.replace(day=1))[0], day_bounds(today)[1], "this month"
    if re.search(r"last 30 days|past month|30 days|last month", text):
        return day_bounds(today - timedelta(days=29))[0], day_bounds(today)[1], "the last 30 days"
    if re.search(r"all time|ever|overall", text):
        return datetime(2000, 1, 1), day_bounds(today)[1], "all time"
    return day_bounds(today - timedelta(days=6))[0], day_bounds(today)[1], "the last 7 days"


def _prev(start: datetime, end: datetime) -> tuple[datetime, datetime]:
    return start - (end - start), start


def _units(db: Session, orders: list[Order]) -> Counter:
    c: Counter = Counter()
    if orders:
        for oi in db.query(OrderItem).filter(OrderItem.order_id.in_([o.id for o in orders])).all():
            c[oi.menu_item_id] += oi.quantity
    return c


def _pct(new: float, old: float) -> str:
    if not old:
        return "no comparison data"
    d = round(100 * (new - old) / old)
    return f"{'up' if d >= 0 else 'down'} {abs(d)}%"


def _result(answer, intent, period, rows=None, chart=None, basis=""):
    return {"answer": answer, "intent": intent, "period": period, "rows": rows or [], "chart": chart, "basis": basis}


def answer(db: Session, question: str) -> dict:
    t = " ".join(question.lower().replace("’", "'").split())
    today = local_now().date()
    start, end, label = resolve_period(t, today)
    orders = valid_orders(db, start, end)
    compare = bool(re.search(r"\b(compare|vs|versus|than|against|growth|change|difference)\b", t))
    menu = [{"id": m.id, "name": m.name} for m in db.query(MenuItem).all()]
    names = {m["id"]: m["name"] for m in menu}

    dish = match_dish_names(t, menu)
    if dish and re.search(r"\b(sold|sell|ordered|orders|sales|how many|revenue|units)\b", t):
        u = _units(db, orders)[dish[0]]
        price = db.get(MenuItem, dish[0]).price
        return _result(f"{names[dish[0]]}: {u} portion(s) ordered {label}, worth {inr(u * price)}.", "dish", label,
                       [{"label": names[dish[0]], "value": u}], None, "Σ quantity of this dish in non-cancelled orders")
    if "cancel" in t:
        allo = db.query(Order).filter(Order.created_at >= start, Order.created_at < end).all()
        c = sum(1 for o in allo if o.status == "cancelled")
        return _result(f"{c} of {len(allo)} orders were cancelled {label}" + (f" ({round(100 * c / len(allo))}%)." if allo else "."), "cancellations", label,
                       basis="cancelled / all orders in the period")
    if re.search(r"\b(rating|ratings|feedback|satisf|review|stars?)\b", t):
        fb = db.query(Feedback).filter(Feedback.created_at >= start, Feedback.created_at < end).all()
        if not fb:
            return _result(f"No ratings were recorded {label}.", "rating", label)
        avg = sum(f.rating for f in fb) / len(fb)
        dist = Counter(f.rating for f in fb)
        return _result(f"Average rating {label} is {avg:.2f}/5 from {len(fb)} ratings; {sum(1 for f in fb if not f.resolved)} still need follow-up.", "rating", label,
                       [{"label": f"{s}★", "value": dist.get(s, 0)} for s in range(5, 0, -1)], "bar", "mean of guest ratings in the period")
    if re.search(r"\b(unmet|missing|asked for|don't have|do not have|not on the menu|requests)\b", t):
        from services.insights_service import unmet_demand_summary
        u = unmet_demand_summary(db, 5)
        if not u:
            return _result("No unmet guest requests have been recorded.", "unmet", "all time")
        return _result("Guests asked for things we couldn't match: " + "; ".join(f"“{x['request']}” ({x['count']}×)" for x in u) + ".", "unmet", "all time",
                       [{"label": x["request"], "value": x["count"]} for x in u], "bar", "searches that returned no dish")
    if re.search(r"\b(category|categories|section)\b", t):
        u = _units(db, orders)
        by: Counter = Counter()
        cats = dict(db.query(MenuItem.id, MenuItem.category).all())
        prices = dict(db.query(MenuItem.id, MenuItem.price).all())
        for i, q in u.items():
            by[cats.get(i, "?")] += q * prices.get(i, 0)
        tot = sum(by.values())
        if not tot:
            return _result(f"No sales {label}.", "category", label)
        rows = [{"label": c, "value": v} for c, v in by.most_common()]
        return _result(f"{rows[0]['label']} led {label} with {round(100 * rows[0]['value'] / tot)}% of sales value.", "category", label, rows, "bar", "Σ quantity × current price by category")
    if re.search(r"\b(busiest|peak|rush|crowded|best time|busy hour)\b", t):
        hrs = Counter(to_local(o.created_at).hour for o in orders)
        days = Counter(to_local(o.created_at).weekday() for o in orders)
        if not hrs:
            return _result(f"No orders {label}.", "peak", label)
        top = hrs.most_common(3)
        return _result(f"Busiest hours {label}: " + ", ".join(f"{h:02d}:00 ({n} orders)" for h, n in top) + f". Busiest day: {DAYS[days.most_common(1)[0][0]]}.", "peak", label,
                       [{"label": f"{h:02d}:00", "value": hrs.get(h, 0)} for h in range(24)], "bar", "orders grouped by local hour")
    if re.search(r"\b(worst|least|never|slow(est)?[- ]moving|underperform|don't sell|dont sell|not selling)\b", t):
        u = _units(db, orders)
        avail = db.query(MenuItem).filter(MenuItem.available.is_(True)).all()
        low = sorted(avail, key=lambda m: (u[m.id], m.id))[:5]
        return _result(f"Slowest sellers {label}: " + ", ".join(f"{m.name} ({u[m.id]})" for m in low) + ".", "worst_dishes", label,
                       [{"label": m.name, "value": u[m.id]} for m in low], "bar", "available dishes ranked by units sold, ascending")
    if re.search(r"\b(top|best|most popular|most ordered|best[- ]selling|bestseller|popular)\b", t):
        u = _units(db, orders)
        if not u:
            return _result(f"No orders {label}.", "top_dishes", label)
        rows = [{"label": names.get(i, "?"), "value": q} for i, q in u.most_common(5)]
        return _result(f"Top dishes {label}: " + ", ".join(f"{r['label']} ({r['value']})" for r in rows) + ".", "top_dishes", label, rows, "bar", "dishes ranked by units sold")
    if re.search(r"\b(average order|avg order|order value|ticket|basket)\b", t):
        if not orders:
            return _result(f"No orders {label}.", "aov", label)
        aov = sum(o.total_amount for o in orders) / len(orders)
        return _result(f"Average order value {label} is {inr(aov)} across {len(orders)} orders.", "aov", label, basis="total revenue / number of orders")
    if re.search(r"\b(how many orders|number of orders|order count|orders)\b", t) and not re.search(r"\b(revenue|sales)\b", t):
        s = f"{len(orders)} orders {label}."
        if compare:
            p = valid_orders(db, *_prev(start, end))
            s += f" That is {_pct(len(orders), len(p))} versus the previous period ({len(p)})."
        return _result(s, "orders", label, basis="non-cancelled orders in the period")
    if re.search(r"\b(revenue|sales|earn|earned|income|money|turnover|made)\b", t):
        rev = sum(o.total_amount for o in orders)
        s = f"Revenue {label} is {inr(rev)} from {len(orders)} orders."
        rows = [{"label": label, "value": rev}]
        if compare or "last week" in t and "this week" in t:
            p = valid_orders(db, *_prev(start, end))
            prev_rev = sum(o.total_amount for o in p)
            s += f" That is {_pct(rev, prev_rev)} versus the previous period ({inr(prev_rev)})."
            rows.append({"label": "previous period", "value": prev_rev})
        return _result(s, "revenue", label, rows, "bar", "Σ total_amount of non-cancelled orders")
    if re.search(r"\b(late|delay|delayed|speed|kitchen|prep time|how fast)\b", t):
        o = operations_summary(db)
        if not o["samples"]:
            return _result("No timed orders yet, so I can't measure kitchen speed.", "kitchen_speed", "all time")
        return _result(f"Orders take {o['avg_minutes_to_ready']} min on average to be ready (median {o['median_minutes_to_ready']}), "
                       f"and {o['on_time_rate_pct']}% are ready within their estimate ({o['samples']} orders).", "kitchen_speed", "all time", basis="placed → ready status timestamps")
    if re.search(r"\b(stock|inventory|running low|sold out)\b", t):
        inv = inventory_summary(db)
        return _result(f"{len(inv['sold_out'])} sold out, {len(inv['low_stock'])} low across {inv['tracked']} tracked dishes.", "inventory", "now")
    return _result(HELP, "help", label)
