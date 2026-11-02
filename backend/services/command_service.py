"""Owner Command Center analytics. Every number comes from real rows (orders, items, status
events, feedback). Forecasts and simulations are labelled as such, and refuse to guess with
too little data."""
import heapq
import math
import random
from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta
from statistics import median

from sqlalchemy.orm import Session

import config
from models import Feedback, MenuItem, Order, OrderItem, OrderStatusEvent, UnmetDemand
from services.kitchen_service import get_kitchen_load, prep_minutes_for
from services.ops_service import feedback_summary, inventory_summary
from services.time_utils import local_now, to_local

OFFSET = timedelta(minutes=config.RESTAURANT_UTC_OFFSET_MINUTES)
DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def day_bounds(d: date) -> tuple[datetime, datetime]:
    start = datetime.combine(d, time.min) - OFFSET
    return start, start + timedelta(days=1)


def valid_orders(db: Session, start: datetime | None = None, end: datetime | None = None) -> list[Order]:
    q = db.query(Order).filter(Order.status != "cancelled")
    if start is not None:
        q = q.filter(Order.created_at >= start)
    if end is not None:
        q = q.filter(Order.created_at < end)
    return q.all()


def inr(n) -> str:
    return f"₹{int(round(n)):,}"


# ------------------------------------------------------------------ pulse
def pulse(db: Session) -> dict:
    now = local_now()
    today = now.date()
    orders = valid_orders(db, day_bounds(today - timedelta(days=13))[0])
    per_day: dict[date, dict] = defaultdict(lambda: {"orders": 0, "revenue": 0})
    for o in orders:
        d = to_local(o.created_at).date()
        per_day[d]["orders"] += 1
        per_day[d]["revenue"] += o.total_amount
    series = [{"date": (today - timedelta(days=i)).isoformat(), "orders": per_day[today - timedelta(days=i)]["orders"],
              "revenue": per_day[today - timedelta(days=i)]["revenue"]} for i in range(13, -1, -1)]
    t = per_day[today]
    last_week = [o for o in orders if to_local(o.created_at).date() == today - timedelta(days=7)
                 and to_local(o.created_at).time() <= now.time()]
    lw_rev = sum(o.total_amount for o in last_week)
    vs = round(100 * (t["revenue"] - lw_rev) / lw_rev) if lw_rev > 0 else None
    start, end = day_bounds(today)
    ratings = [f.rating for f in db.query(Feedback).filter(Feedback.created_at >= start, Feedback.created_at < end).all()]
    load = get_kitchen_load(db)
    return {"as_of": now.isoformat(), "revenue_today": t["revenue"], "orders_today": t["orders"],
            "avg_order_value": round(t["revenue"] / t["orders"]) if t["orders"] else None,
            "revenue_vs_last_week_pct": vs, "last_week_revenue_same_time": lw_rev,
            "rating_today": round(sum(ratings) / len(ratings), 2) if ratings else None, "ratings_today": len(ratings),
            "kitchen": load, "series": series}


# ------------------------------------------------------------------ heatmap + forecast
def _grid(orders: list[Order]) -> list[list[int]]:
    grid = [[0] * 24 for _ in range(7)]
    for o in orders:
        l = to_local(o.created_at)
        grid[l.weekday()][l.hour] += 1
    return grid


def heatmap(db: Session, days: int = 28) -> dict:
    today = local_now().date()
    orders = valid_orders(db, day_bounds(today - timedelta(days=days - 1))[0])
    grid = _grid(orders)
    return {"days": DAYS, "grid": grid, "max": max(max(r) for r in grid), "orders": len(orders), "window_days": days}


def avg_prep_per_order(db: Session, orders: list[Order]) -> float:
    if not orders:
        return 12.0
    ids = [o.id for o in orders]
    total = 0.0
    items = {m.id: m for m in db.query(MenuItem).all()}
    for oi in db.query(OrderItem).filter(OrderItem.order_id.in_(ids)).all():
        m = items.get(oi.menu_item_id)
        total += (prep_minutes_for(m) if m else 10) * oi.quantity
    return total / len(orders)


def forecast(db: Session) -> dict:
    now = local_now()
    today = now.date()
    all_orders = valid_orders(db, day_bounds(today - timedelta(days=28))[0])
    past = [o for o in all_orders if to_local(o.created_at).date() < today]
    days_seen = len({to_local(o.created_at).date() for o in past})
    sufficient = len(past) >= 50 and days_seen >= 14
    if not past:
        return {"available": False, "reason": "No order history yet.", "hours": []}
    first = min(to_local(o.created_at).date() for o in past)
    occ = Counter((first + timedelta(days=i)).weekday() for i in range((today - first).days))
    grid = _grid(past)
    per_order = avg_prep_per_order(db, past)
    hours = []
    for k in range(24):
        dt = now + timedelta(hours=k)
        w, h = dt.weekday(), dt.hour
        expected = grid[w][h] / occ[w] if occ[w] else 0
        workload = expected * per_order * 0.6
        stations = max(1, math.ceil(workload / 60 / 0.7)) if expected > 0.05 else 1
        hours.append({"hour": h, "weekday": DAYS[w], "label": dt.strftime("%a %H:00"), "expected_orders": round(expected, 1),
                      "recommended_stations": stations})
    peak = max(hours, key=lambda x: x["expected_orders"])
    return {"available": sufficient, "reason": None if sufficient else f"Only {len(past)} orders over {days_seen} days; need 50+ orders over 14+ days for a reliable forecast.",
            "method": "average of the same weekday and hour over recent weeks (naive seasonal baseline)", "hours": hours, "peak": peak,
            "basis": f"stations = ceil(expected orders × {per_order:.1f} prep-min × 0.6 parallelism / 60 / 0.7 target utilisation)"}


# ------------------------------------------------------------------ alerts
def alerts(db: Session) -> list[dict]:
    out: list[dict] = []
    add = lambda sev, typ, title, detail, ev=None: out.append({"severity": sev, "type": typ, "title": title, "detail": detail, "evidence": ev or {}})
    now = local_now()
    today = now.date()
    load = get_kitchen_load(db)
    if load["late_orders"] >= 2:
        add("critical" if load["late_orders"] >= 4 else "warning", "late_orders", f"{load['late_orders']} orders are running late",
            "Open the kitchen board and prioritise the oldest tickets.", {"late": load["late_orders"]})
    if load["level"] == "busy":
        add("warning", "kitchen_busy", "Kitchen is busy", f"About {load['estimated_wait_minutes']} min before a new order starts.", {"wait": load["estimated_wait_minutes"]})
    if load["stale_orders"]:
        add("info", "stale_orders", f"{load['stale_orders']} old order(s) still open", "They are excluded from wait times. Complete or cancel them.", {"stale": load["stale_orders"]})
    fb = feedback_summary(db)
    if fb["needs_follow_up"]:
        add("warning", "feedback", f"{fb['needs_follow_up']} low rating(s) need follow-up", "Review them in the feedback panel.", {"count": fb["needs_follow_up"]})
    recent = [r["rating"] for r in fb["recent"][:10]]
    if fb["count"] >= 10 and len(recent) >= 10 and fb["average"] - sum(recent) / len(recent) >= 0.8:
        add("warning", "rating_dip", "Ratings are dipping", f"Last 10 average {sum(recent)/10:.1f} vs overall {fb['average']}.", {"recent": sum(recent) / 10, "overall": fb["average"]})
    inv = inventory_summary(db)
    top = Counter()
    for oi, o in db.query(OrderItem, Order).join(Order, Order.id == OrderItem.order_id).filter(Order.status != "cancelled", Order.created_at >= datetime.utcnow() - timedelta(days=30)):
        top[oi.menu_item_id] += oi.quantity
    top5 = {i for i, _ in top.most_common(5)}
    for m in inv["sold_out"]:
        add("critical" if m["id"] in top5 else "warning", "sold_out", f"{m['name']} is sold out", "Top seller: restock urgently." if m["id"] in top5 else "Restock when possible.", m)
    for m in inv["low_stock"]:
        add("warning", "low_stock", f"{m['name']}: only {m['stock']} left", "Below the low-stock threshold.", m)
    # Revenue pace vs the same weekday over the previous 4 weeks, at the same time of day.
    base = []
    for w in range(1, 5):
        d = today - timedelta(days=7 * w)
        s, _ = day_bounds(d)
        base.append(sum(o.total_amount for o in valid_orders(db, s, s + timedelta(hours=now.hour, minutes=now.minute))))
    start, end = day_bounds(today)
    so_far = sum(o.total_amount for o in valid_orders(db, start, end))
    avg = sum(base) / 4
    if avg >= 1000 and now.hour >= 13 and so_far < 0.6 * avg:
        add("warning", "revenue_pace", "Revenue is behind pace", f"{inr(so_far)} so far vs {inr(avg)} typical by now ({round(100 * so_far / avg)}%).", {"so_far": so_far, "typical": round(avg)})
    unmet = db.query(UnmetDemand.filters).count()
    if unmet >= 3:
        add("info", "unmet_demand", f"{unmet} guest requests had no match", "See 'requests we couldn't serve' for what to add.", {"count": unmet})
    order = {"critical": 0, "warning": 1, "info": 2}
    return sorted(out, key=lambda a: order[a["severity"]])


# ------------------------------------------------------------------ menu engineering
def menu_engineering(db: Session, days: int = 30) -> dict:
    start = datetime.utcnow() - timedelta(days=days)
    units: Counter = Counter()
    for oi, o in db.query(OrderItem, Order).join(Order, Order.id == OrderItem.order_id).filter(Order.status != "cancelled", Order.created_at >= start):
        units[oi.menu_item_id] += oi.quantity
    items = db.query(MenuItem).filter(MenuItem.archived.is_(False)).all()
    with_cost = [m for m in items if m.cost_price is not None]
    use_margin = len(with_cost) >= 0.6 * len(items) and len(items) > 0
    rows = []
    for m in items:
        value = (m.price - (m.cost_price or 0)) if use_margin and m.cost_price is not None else m.price
        rows.append({"id": m.id, "name": m.name, "category": m.category, "price": m.price, "units": units[m.id], "value": value,
                     "revenue": units[m.id] * m.price, "profit": units[m.id] * (m.price - m.cost_price) if m.cost_price is not None else None})
    total_units = sum(r["units"] for r in rows)
    if not rows:
        return {"sufficient": False, "items": []}
    pop_cut, val_cut = median([r["units"] for r in rows]), median([r["value"] for r in rows])
    tips = {"star": "Keep prominent: popular and valuable.", "workhorse": "Popular but low value: try a small price rise or pair with an add-on.",
            "puzzle": "Valuable but under-ordered: promote it or move it up the menu.", "dog": "Low demand, low value: rework, replace or remove."}
    for r in rows:
        hi_pop, hi_val = r["units"] > pop_cut or (r["units"] == pop_cut and pop_cut > 0), r["value"] >= val_cut
        r["quadrant"] = "star" if hi_pop and hi_val else "workhorse" if hi_pop else "puzzle" if hi_val else "dog"
        r["advice"] = tips[r["quadrant"]]
    return {"sufficient": total_units >= 30, "days": days, "basis": "margin per unit (cost prices set)" if use_margin else "price per unit (set cost prices for true margin analysis)",
            "popularity_cut": pop_cut, "value_cut": val_cut, "items": rows, "total_units": total_units}


# ------------------------------------------------------------------ combos
def _baskets(db: Session) -> tuple[list[set[int]], Counter]:
    by_order: dict[int, set[int]] = defaultdict(set)
    ids = [i for (i,) in db.query(Order.id).filter(Order.status != "cancelled").all()]
    for oi in db.query(OrderItem).filter(OrderItem.order_id.in_(ids or [0])).all():
        by_order[oi.order_id].add(oi.menu_item_id)
    baskets = list(by_order.values())
    singles: Counter = Counter()
    for b in baskets:
        singles.update(b)
    return baskets, singles


def combo_stats(db: Session) -> list[dict]:
    baskets, singles = _baskets(db)
    n = len(baskets)
    pairs: Counter = Counter()
    for b in baskets:
        for a in b:
            for c in b:
                if a != c:
                    pairs[(a, c)] += 1
    names = dict(db.query(MenuItem.id, MenuItem.name).all())
    out = []
    for (a, c), cnt in pairs.items():
        if cnt < 3:
            continue
        conf = cnt / singles[a]
        lift = conf / (singles[c] / n)
        out.append({"if_item": a, "then_item": c, "if_name": names.get(a), "then_name": names.get(c), "orders_together": cnt,
                    "confidence_pct": round(100 * conf), "lift": round(lift, 2), "of_orders": singles[a]})
    return sorted(out, key=lambda x: (-x["lift"], -x["orders_together"]))


def combos(db: Session) -> dict:
    n = db.query(Order).filter(Order.status != "cancelled").count()
    return {"sufficient": n >= 30, "orders": n, "combos": combo_stats(db)[:8] if n >= 30 else [],
            "note": "confidence = how often guests who ordered the first dish also ordered the second; lift > 1 means more often than chance"}


def best_companion(db: Session, cart_ids: set[int], exclude: set[int], max_price: int | None, diet: str | None) -> dict | None:
    if db.query(Order).filter(Order.status != "cancelled").count() < 30:
        return None
    for c in combo_stats(db):
        if c["if_item"] in cart_ids and c["then_item"] not in exclude and c["lift"] >= 1.15 and c["confidence_pct"] >= 25:
            item = db.get(MenuItem, c["then_item"])
            if item is None or not item.available or (item.stock_quantity is not None and item.stock_quantity <= 0):
                continue
            if max_price is not None and item.price > max_price:
                continue
            if diet and diet.lower() not in [t.lower() for t in (item.dietary_tags or [])]:
                continue
            return {**c, "item": item}
    return None


# ------------------------------------------------------------------ rush simulator
def _pct(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    v = sorted(values)
    return v[min(len(v) - 1, math.ceil(p / 100 * len(v)) - 1)]


def _run_sim(menu, weights, orders, minutes, stations, seed, backlog):
    rng = random.Random(seed)
    arrivals = sorted(rng.uniform(0, minutes) for _ in range(orders))
    free = [backlog] * stations
    heapq.heapify(free)
    recs = []
    for a in arrivals:
        picked = rng.choices(menu, weights=weights, k=rng.randint(1, 3))
        work = sum(prep_minutes_for(m) for m in picked) * 0.6 * rng.uniform(0.8, 1.2)
        s = heapq.heappop(free)
        start = max(s, a)
        heapq.heappush(free, start + work)
        recs.append((a, start, start + work))
    return recs


def simulate_rush(db: Session, orders: int = 20, minutes: int = 10, stations: int | None = None, seed: int = 7) -> dict:
    orders, minutes = max(1, min(orders, 300)), max(1, min(minutes, 240))
    stations = max(1, min(stations or config.KITCHEN_PARALLEL_STATIONS, 20))
    menu = db.query(MenuItem).filter(MenuItem.available.is_(True)).all()
    if not menu:
        return {"error": "No available dishes to simulate."}
    sold: Counter = Counter()
    for oi in db.query(OrderItem).all():
        sold[oi.menu_item_id] += oi.quantity
    weights = [sold[m.id] + 1 for m in menu]
    backlog = get_kitchen_load(db)["estimated_wait_minutes"]
    sla = config.SLA_MINUTES

    def summarize(st):
        recs = _run_sim(menu, weights, orders, minutes, st, seed, backlog)
        waits = [s - a for a, s, _ in recs]
        totals = [e - a for a, _, e in recs]
        return recs, waits, totals, round(100 * sum(1 for t in totals if t > sla) / len(totals))

    recs, waits, totals, over = summarize(stations)
    horizon = int(math.ceil(max(e for _, _, e in recs))) + 1
    timeline = [{"minute": m, "waiting": sum(1 for a, s, _ in recs if a <= m < s), "cooking": sum(1 for _, s, e in recs if s <= m < e)}
                for m in range(0, min(horizon, 240) + 1)]
    needed = next((st for st in range(1, 21) if summarize(st)[3] <= 10), None)
    verdict = (f"With {stations} station(s), {over}% of orders would miss the {sla}-minute target." if over else
               f"With {stations} station(s) every order is ready within {sla} minutes.")
    if needed and needed > stations:
        verdict += f" You would need about {needed} stations to keep 90% within target."
    return {"scenario": {"orders": orders, "minutes": minutes, "stations": stations, "starting_backlog_minutes": backlog, "target_minutes": sla},
            "avg_wait_min": round(sum(waits) / len(waits), 1), "p90_total_min": round(_pct(totals, 90), 1), "max_wait_min": round(max(waits), 1),
            "pct_over_target": over, "stations_needed": needed, "timeline": timeline, "verdict": verdict,
            "method": "Monte Carlo-style queue simulation with a fixed random seed (repeatable). Prep times are the configured estimates; this is a scenario, not a prediction."}


# ------------------------------------------------------------------ floor + activity
def floor(db: Session) -> dict:
    now = datetime.utcnow()
    tables = []
    for n in range(1, config.TABLE_COUNT + 1):
        o = (db.query(Order).filter(Order.order_type == "dine_in", Order.table_number == str(n), Order.status != "cancelled")
             .order_by(Order.id.desc()).first())
        state, info = "free", None
        if o:
            age = (now - o.created_at).total_seconds() / 60
            if o.status == "pending":
                state = "ordered"
            elif o.status == "preparing":
                state = "cooking"
            elif o.status == "ready":
                state = "serve"
            elif o.status == "completed" and age < 60:
                ev = db.query(OrderStatusEvent).filter(OrderStatusEvent.order_id == o.id, OrderStatusEvent.status == "completed").first()
                if ev and (now - ev.created_at).total_seconds() < 20 * 60:
                    state = "dining"
            if state != "free" and age < config.STALE_ORDER_HOURS * 60:
                info = {"order_id": o.id, "name": o.customer_name.split()[0], "minutes": round(age)}
            else:
                state = "free"
        tables.append({"table": n, "state": state, "info": info})
    return {"tables": tables, "counts": dict(Counter(t["state"] for t in tables))}


def activity(db: Session, limit: int = 25) -> list[dict]:
    ev: list[tuple[datetime, str, str]] = []
    names = {o.id: o for o in db.query(Order).order_by(Order.id.desc()).limit(200).all()}
    for o in list(names.values())[:40]:
        ev.append((o.created_at, "order", f"New order #{o.id} from {o.customer_name.split()[0]} ({inr(o.total_amount)})" + (" · demo" if o.is_demo else "")))
    for e in db.query(OrderStatusEvent).filter(OrderStatusEvent.status != "pending").order_by(OrderStatusEvent.id.desc()).limit(40).all():
        o = names.get(e.order_id)
        if o:
            ev.append((e.created_at, "status", f"Order #{o.id} {e.status}"))
    for f in db.query(Feedback).order_by(Feedback.id.desc()).limit(15).all():
        ev.append((f.created_at, "feedback", f"{'★' * f.rating} rating for order #{f.order_id}" + (f": “{f.comment[:60]}”" if f.comment else "")))
    for u in db.query(UnmetDemand).order_by(UnmetDemand.id.desc()).limit(10).all():
        ev.append((u.created_at, "unmet", f"Guest asked for something we couldn't match: “{u.query_text[:60]}”"))
    ev.sort(key=lambda x: x[0], reverse=True)
    return [{"at": t.isoformat() + "Z", "kind": k, "text": s} for t, k, s in ev[:limit]]


# ------------------------------------------------------------------ morning briefing
def briefing(db: Session) -> dict:
    today = local_now().date()
    y = today - timedelta(days=1)
    ys, ye = day_bounds(y)
    yo = valid_orders(db, ys, ye)
    lines: list[str] = []
    if yo:
        rev = sum(o.total_amount for o in yo)
        top = Counter()
        for oi in db.query(OrderItem).filter(OrderItem.order_id.in_([o.id for o in yo])).all():
            top[oi.menu_item_id] += oi.quantity
        name = db.get(MenuItem, top.most_common(1)[0][0]).name
        lw_s, lw_e = day_bounds(y - timedelta(days=7))
        lw = sum(o.total_amount for o in valid_orders(db, lw_s, lw_e))
        cmp_txt = f", {'up' if rev >= lw else 'down'} {abs(round(100 * (rev - lw) / lw))}% on the same day last week" if lw else ""
        lines.append(f"Yesterday you served {len(yo)} orders and earned {inr(rev)}{cmp_txt}. The most ordered dish was {name}.")
    else:
        lines.append("There were no orders yesterday.")
    fc = forecast(db)
    if fc.get("available"):
        p = fc["peak"]
        lines.append(f"Expect the busiest hour around {p['label']} with roughly {p['expected_orders']} orders; plan for {p['recommended_stations']} cooking stations.")
    al = alerts(db)
    if al:
        lines.append(f"{len(al)} alert(s) need attention. Most important: {al[0]['title']}.")
    else:
        lines.append("No alerts right now. Everything looks healthy.")
    fb = feedback_summary(db)
    if fb["needs_follow_up"]:
        lines.append(f"{fb['needs_follow_up']} guest rating(s) need a follow-up.")
    return {"date": today.isoformat(), "lines": lines, "speech": " ".join(lines)}
