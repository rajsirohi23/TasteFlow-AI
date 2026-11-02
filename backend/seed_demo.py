"""Generate clearly-labelled DEMO orders so dashboards, forecasts and feedback have
something to show during a presentation.

  python seed_demo.py              # add ~14 days of demo history
  python seed_demo.py --days 21 --orders 300
  python seed_demo.py --clear      # remove ONLY demo rows (real orders untouched)

Every row is flagged is_demo=True and the owner insights say so. The data is
simulated (timings, ratings, comments), so never present it as real guests.
"""
import argparse
import random
import secrets
from datetime import datetime, timedelta

import config
from database import SessionLocal
from migrate import upgrade_schema
from database import engine
from models import Feedback, MenuItem, Order, OrderItem, OrderStatusEvent

GOOD = ["Loved it, so fresh", "Delicious and quick", "Great flavours", "Perfect, will order again", ""]
BAD = ["Food was cold and the wait was long", "Very slow, took forever", "Bland and a bit oily", "Order was wrong, item missing", "Staff were rude"]


def clear(db) -> int:
    ids = [o.id for o in db.query(Order.id).filter(Order.is_demo.is_(True)).all()]
    if ids:
        db.query(Feedback).filter(Feedback.order_id.in_(ids)).delete(synchronize_session=False)
        db.query(OrderStatusEvent).filter(OrderStatusEvent.order_id.in_(ids)).delete(synchronize_session=False)
        db.query(OrderItem).filter(OrderItem.order_id.in_(ids)).delete(synchronize_session=False)
        db.query(Order).filter(Order.id.in_(ids)).delete(synchronize_session=False)
        db.commit()
    return len(ids)


def seed(db, days: int, count: int, seed_value: int = 42) -> int:
    rng = random.Random(seed_value)
    menu = db.query(MenuItem).filter(MenuItem.available.is_(True)).all()
    if not menu:
        raise SystemExit("Menu is empty. Run init_db.py first.")
    drinks = [m for m in menu if m.category == "Drinks"]
    desserts = [m for m in menu if m.category == "Desserts"]
    weights = [rng.uniform(0.5, 3.0) for _ in menu]          # some dishes are naturally more popular
    names = ["Aarav", "Diya", "Kabir", "Ananya", "Rohan", "Isha", "Vihaan", "Meera", "Arjun", "Sara", "Neha", "Karan"]
    offset = timedelta(minutes=config.RESTAURANT_UTC_OFFSET_MINUTES)
    now_local = datetime.utcnow() + offset
    made = 0
    for _ in range(count):
        day = now_local.date() - timedelta(days=rng.randint(0, days - 1))
        hour = rng.choices([8, 12, 13, 14, 16, 19, 20, 21, 22], weights=[1, 5, 6, 3, 1, 5, 7, 5, 1])[0]
        placed_local = datetime(day.year, day.month, day.day, hour, rng.randint(0, 59), rng.randint(0, 59))
        if placed_local > now_local - timedelta(minutes=45):
            continue
        placed = placed_local - offset
        picked = rng.choices(menu, weights=weights, k=rng.randint(1, 4))
        lines: dict[int, int] = {}
        for m in picked:
            lines[m.id] = lines.get(m.id, 0) + rng.randint(1, 2)
        # Simulated habit: mains often come with a drink, starters with a dessert (so combo analysis has a signal).
        for m in list(picked):
            pool = drinks if m.category == "Main Course" else desserts if m.category == "Starters" else []
            if pool and rng.random() < (0.55 if m.category == "Main Course" else 0.3):
                mate = pool[m.id % len(pool)]
                lines[mate.id] = lines.get(mate.id, 0) + 1
        total = sum(next(m.price for m in menu if m.id == i) * q for i, q in lines.items())
        eta = rng.randint(12, 20)
        cancelled = rng.random() < 0.05
        order = Order(customer_name=rng.choice(names), status="cancelled" if cancelled else "completed", total_amount=total,
                      created_at=placed, source="web", is_demo=True, tracking_code=secrets.token_hex(4).upper(), eta_minutes=eta,
                      order_type=rng.choice(["takeaway", "dine_in"]))
        db.add(order)
        db.flush()
        for i, q in lines.items():
            db.add(OrderItem(order_id=order.id, menu_item_id=i, quantity=q, unit_price=next(m.price for m in menu if m.id == i)))
        db.add(OrderStatusEvent(order_id=order.id, status="pending", created_at=placed))
        if cancelled:
            db.add(OrderStatusEvent(order_id=order.id, status="cancelled", created_at=placed + timedelta(minutes=rng.randint(1, 3))))
        else:
            start = placed + timedelta(minutes=rng.randint(1, 4))
            late = rng.random() < 0.2
            ready = placed + timedelta(minutes=eta + rng.randint(2, 9) if late else rng.randint(7, max(8, eta - 1)))
            done = ready + timedelta(minutes=rng.randint(1, 8))
            for st, at in (("preparing", start), ("ready", ready), ("completed", done)):
                db.add(OrderStatusEvent(order_id=order.id, status=st, created_at=at))
            if rng.random() < 0.45:
                rating = rng.choice([1, 2, 2, 3]) if late and rng.random() < 0.8 else rng.choice([3, 4, 4, 5, 5, 5])
                comment = rng.choice(BAD if rating <= 2 else GOOD)
                from services.feedback_service import analyze
                sentiment, topics = analyze(rating, comment)
                db.add(Feedback(order_id=order.id, rating=rating, comment=comment or None, sentiment=sentiment,
                                topics=topics, resolved=rating > 2 or rng.random() < 0.3, created_at=done))
        made += 1
    db.commit()
    return made


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", type=int, default=14)
    ap.add_argument("--orders", type=int, default=180)
    ap.add_argument("--clear", action="store_true", help="remove demo rows only")
    a = ap.parse_args()
    upgrade_schema(engine)
    with SessionLocal() as db:
        if a.clear:
            print(f"Removed {clear(db)} demo orders (and their events/feedback).")
        else:
            clear(db)  # idempotent: re-running replaces earlier demo data
            print(f"Created {seed(db, a.days, a.orders)} DEMO orders over {a.days} days (flagged is_demo=True).")
            print("Reminder: this is simulated data. Say so in your presentation.")
