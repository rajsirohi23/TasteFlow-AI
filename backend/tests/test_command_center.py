"""Owner Command Center, Copilot, Hindi understanding and combo-driven suggestions."""
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import seed_demo
from agents.nlu import normalize_hindi, parse_message
from auth import create_token
from database import Base, get_db
from init_db import load_demo_menu
from main import app
from models import MenuItem, Order, OrderItem
from services.command_service import day_bounds, valid_orders
from services.time_utils import local_today

ANON = {"Authorization": ""}
OWNER = {"Authorization": f"Bearer {create_token('owner')}"}
KITCHEN = {"Authorization": f"Bearer {create_token('kitchen')}"}


@pytest.fixture()
def env():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    with Session() as db:
        db.add_all(MenuItem(**r) for r in load_demo_menu())
        db.commit()

    def override():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override
    yield TestClient(app), Session
    app.dependency_overrides.clear()


@pytest.fixture()
def seeded(env):
    client, Session = env
    with Session() as db:
        seed_demo.seed(db, days=21, count=320)
    return client, Session


def get(client, path, headers=OWNER, **kw):
    return client.get(path, headers=headers, **kw)


ENDPOINTS = ["pulse", "heatmap", "forecast", "alerts", "menu-engineering", "combos", "simulate-rush", "floor", "activity", "briefing"]


@pytest.mark.parametrize("name", ENDPOINTS)
def test_command_endpoints_need_owner_login(env, name):
    client, _ = env
    assert get(client, f"/api/owner/{name}", ANON).status_code == 401
    assert get(client, f"/api/owner/{name}", KITCHEN).status_code == 403
    assert get(client, f"/api/owner/{name}").status_code == 200


def test_copilot_requires_owner(env):
    client, _ = env
    assert client.post("/api/owner/copilot", json={"question": "revenue today"}, headers=ANON).status_code == 401


def test_pulse_reflects_a_real_order_and_has_14_day_series(env):
    client, _ = env
    r = client.post("/api/orders", json={"customer_name": "Ravi", "items": [{"menu_item_id": 1, "quantity": 2}]}, headers=ANON).json()
    p = get(client, "/api/owner/pulse").json()
    assert len(p["series"]) == 14 and p["series"][-1]["orders"] == 1
    assert p["revenue_today"] == r["total_amount"] and p["orders_today"] == 1 and p["avg_order_value"] == r["total_amount"]


def test_heatmap_totals_match_orders(seeded):
    client, Session = seeded
    h = get(client, "/api/owner/heatmap").json()
    assert len(h["grid"]) == 7 and all(len(row) == 24 for row in h["grid"])
    assert sum(map(sum, h["grid"])) == h["orders"] and h["max"] > 0


def test_forecast_available_with_history_and_honest_without(env, seeded):
    client, _ = seeded
    f = get(client, "/api/owner/forecast").json()
    assert f["available"] is True and len(f["hours"]) == 24 and f["peak"]["expected_orders"] > 0
    assert all(h["recommended_stations"] >= 1 for h in f["hours"]) and "naive" in f["method"]


def test_forecast_refuses_to_guess_without_data(env):
    client, _ = env
    f = get(client, "/api/owner/forecast").json()
    assert f["available"] is False and f["hours"] == []


def test_alerts_late_orders_and_sold_out_top_seller(env):
    client, Session = env
    for _ in range(4):
        client.post("/api/orders", json={"customer_name": "Ravi", "items": [{"menu_item_id": 1, "quantity": 1}]}, headers=ANON)
    with Session() as db:
        for o in db.query(Order).all():
            o.created_at = datetime.utcnow() - timedelta(minutes=(o.eta_minutes or 15) + 10)
        db.commit()
    client.patch("/api/owner/menu/1/stock", json={"stock_quantity": 0}, headers=OWNER)
    a = get(client, "/api/owner/alerts").json()["alerts"]
    types = {x["type"]: x for x in a}
    assert types["late_orders"]["severity"] == "critical" and types["sold_out"]["severity"] == "critical"
    assert a[0]["severity"] == "critical"            # sorted by severity


def test_menu_engineering_quadrants_and_margin_upgrade(seeded):
    client, _ = seeded
    me = get(client, "/api/owner/menu-engineering").json()
    assert me["sufficient"] and "price per unit" in me["basis"]
    assert {i["quadrant"] for i in me["items"]} <= {"star", "workhorse", "puzzle", "dog"} and all(i["advice"] for i in me["items"])
    for item in me["items"]:                         # give every dish a cost -> true margin analysis
        client.patch(f"/api/owner/menu/{item['id']}/cost", json={"cost_price": int(item["price"] * 0.4)}, headers=OWNER)
    me2 = get(client, "/api/owner/menu-engineering").json()
    assert "margin" in me2["basis"] and me2["items"][0]["profit"] is not None


def test_combos_found_and_used_for_suggestions(seeded):
    client, _ = seeded
    c = get(client, "/api/owner/combos").json()
    assert c["sufficient"] and c["combos"] and c["combos"][0]["lift"] > 1
    top = c["combos"][0]
    # Chat: add the "if" dish and the add-on suggestion must cite the real statistic.
    sid = "combo-session-01"
    say = lambda m: client.post("/api/chat", json={"session_id": sid, "message": m}, headers=ANON).json()
    name = top["if_name"]
    r = say(f"add {name}")
    step = next(s for s in r["trace"]["steps"] if s["action"] == "market_basket_lookup")
    assert step["output"]["companion"] and "of guests who ordered" in r["reply"]    # cites the real statistic


def test_rush_simulation_is_repeatable_and_more_stations_help(env):
    client, _ = env
    a = get(client, "/api/owner/simulate-rush", params={"orders": 40, "minutes": 10, "stations": 2, "seed": 3}).json()
    b = get(client, "/api/owner/simulate-rush", params={"orders": 40, "minutes": 10, "stations": 2, "seed": 3}).json()
    assert a == b                                    # deterministic
    more = get(client, "/api/owner/simulate-rush", params={"orders": 40, "minutes": 10, "stations": 8, "seed": 3}).json()
    assert more["avg_wait_min"] <= a["avg_wait_min"] and more["pct_over_target"] <= a["pct_over_target"]
    assert a["stations_needed"] is None or a["stations_needed"] >= 1
    assert "not a prediction" in a["method"] and len(a["timeline"]) > 5
    assert get(client, "/api/owner/simulate-rush", params={"orders": 9999}).status_code == 422


def test_floor_plan_follows_order_status(env):
    client, _ = env
    o = client.post("/api/orders", json={"customer_name": "Ravi", "items": [{"menu_item_id": 1, "quantity": 1}], "order_type": "dine_in", "table_number": "5"}, headers=ANON).json()
    state = lambda: {t["table"]: t["state"] for t in get(client, "/api/owner/floor").json()["tables"]}[5]
    assert state() == "ordered"
    client.patch(f"/api/kitchen/orders/{o['id']}/status", json={"status": "preparing"}, headers=KITCHEN)
    assert state() == "cooking"
    client.patch(f"/api/kitchen/orders/{o['id']}/status", json={"status": "ready"}, headers=KITCHEN)
    assert state() == "serve"
    client.patch(f"/api/kitchen/orders/{o['id']}/status", json={"status": "completed"}, headers=KITCHEN)
    assert state() == "dining"


def test_activity_feed_and_briefing(seeded):
    client, _ = seeded
    ev = get(client, "/api/owner/activity").json()["events"]
    assert ev and {"at", "kind", "text"} <= set(ev[0]) and ev == sorted(ev, key=lambda e: e["at"], reverse=True)
    b = get(client, "/api/owner/briefing").json()
    assert b["lines"] and b["speech"] and ("alert" in b["speech"].lower() or "healthy" in b["speech"].lower())


# ---------------------------------------------------------------- copilot: answers must equal raw DB math
def ask(client, q):
    return client.post("/api/owner/copilot", json={"question": q}, headers=OWNER).json()


def test_copilot_revenue_matches_database(seeded):
    client, Session = seeded
    r = ask(client, "what was the revenue in the last 7 days")
    start, end = day_bounds(local_today() - timedelta(days=6))[0], day_bounds(local_today())[1]
    with Session() as db:
        expected = sum(o.total_amount for o in valid_orders(db, start, end))
    assert r["intent"] == "revenue" and f"{expected:,}" in r["answer"]


def test_copilot_orders_compare_and_top_dishes(seeded):
    client, Session = seeded
    r = ask(client, "how many orders this week vs last week")
    assert r["intent"] == "orders" and "versus the previous period" in r["answer"]
    t = ask(client, "top dishes last 30 days")
    assert t["intent"] == "top_dishes" and len(t["rows"]) == 5 and t["rows"] == sorted(t["rows"], key=lambda x: -x["value"])
    from collections import Counter
    start = day_bounds(local_today() - timedelta(days=29))[0]
    with Session() as db:
        units, names = Counter(), dict(db.query(MenuItem.id, MenuItem.name).all())
        for oi, o in db.query(OrderItem, Order).join(Order, Order.id == OrderItem.order_id).filter(Order.status != "cancelled", Order.created_at >= start):
            units[oi.menu_item_id] += oi.quantity
    expected = [(names[i], q) for i, q in units.most_common(5)]
    assert [(r["label"], r["value"]) for r in t["rows"]] == expected      # matches raw database math


def test_copilot_dish_specific_peak_rating_worst_unmet_and_help(seeded):
    client, Session = seeded
    with Session() as db:
        dish = db.get(MenuItem, 2).name
    d = ask(client, f"how many {dish} did we sell in the last 30 days")
    assert d["intent"] == "dish" and dish in d["answer"]
    assert ask(client, "busiest hour")["intent"] == "peak"
    assert ask(client, "ratings last 30 days")["intent"] == "rating"
    assert ask(client, "which dishes never sell")["intent"] == "worst_dishes"
    assert ask(client, "average order value")["intent"] == "aov"
    assert ask(client, "sales by category")["intent"] == "category"
    assert ask(client, "tell me a joke")["intent"] == "help"


def test_owner_can_ask_copilot_through_chat_and_customers_cannot(seeded):
    client, _ = seeded
    own = client.post("/api/chat", json={"session_id": "own-session-01", "message": "top dishes this week"}, headers=OWNER).json()
    assert own["copilot"]["intent"] == "top_dishes" and any(s["action"] == "answer_business_question" for s in own["trace"]["steps"])
    cust = client.post("/api/chat", json={"session_id": "cus-session-01", "message": "how many orders today"}, headers=ANON).json()
    assert "staff only" in cust["reply"] and cust.get("copilot") is None


# ---------------------------------------------------------------- Hindi / Devanagari voice input
def test_hindi_normalisation_and_intents():
    assert "vegetarian" in normalize_hindi("शाकाहारी खाना") and normalize_hindi("३०० से कम") .strip().endswith("300")
    state = {"pending": None, "cart": [], "last_order_id": 5, "last_shown": []}
    menu = [{"id": 1, "name": "Paneer Tikka"}]
    parse = lambda t, st=state: parse_message(t, st, menu, set())
    r = parse("शाकाहारी खाना 300 के अंदर कम तीखा")
    assert r["intent"] == "recommend" and r["prefs"]["diet"] == "vegetarian" and r["prefs"]["budget"] == 300 and r["prefs"]["max_spice_level"] == "Medium"
    assert parse("मेरा ऑर्डर कहाँ है")["intent"] == "order_status"
    assert parse("ऑर्डर कर दो")["intent"] == "checkout"
    assert parse("हाँ", {**state, "pending": {"type": "confirm_order"}})["intent"] == "confirm_yes"
    assert parse("नहीं", {**state, "pending": {"type": "confirm_order"}})["intent"] == "decline"
    assert parse("कार्ट दिखाओ")["intent"] == "show_cart"


def test_hindi_end_to_end_chat(env):
    client, _ = env
    r = client.post("/api/chat", json={"session_id": "hindi-session-1", "message": "शाकाहारी खाना 300 के अंदर"}, headers=ANON).json()
    assert r["cards"] and r["prefs"]["diet"] == "vegetarian" and all(c["price"] <= 300 for c in r["cards"])
