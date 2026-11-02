"""Tests for tracking, stock, feedback, order details, reorder, inventory and demo data."""
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from auth import create_token
from database import Base, get_db
from init_db import load_demo_menu
from main import app
from models import Feedback, MenuItem, Order, OrderStatusEvent
from services.order_service import set_status

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


def place(client, qty=1, item=1, **extra):
    r = client.post("/api/orders", json={"customer_name": "Ravi Kumar", "items": [{"menu_item_id": item, "quantity": qty}], **extra}, headers=ANON)
    assert r.status_code == 201, r.text
    return r.json()


# ---------------------------------------------------------------- tracking
def test_order_gets_tracking_code_and_eta(env):
    client, _ = env
    o = place(client)
    assert len(o["tracking_code"]) == 8 and o["eta_minutes"] >= 5


def test_tracking_countdown_and_privacy(env):
    client, _ = env
    o = place(client)
    t = client.get(f"/api/track/{o['tracking_code']}", headers=ANON).json()
    assert t["status"] == "pending" and t["state"] == "on_time" and t["is_estimate"] is True
    assert 0 < t["remaining_seconds"] <= o["eta_minutes"] * 60
    assert t["customer_first_name"] == "Ravi" and "Kumar" not in str(t)      # no surname leaked
    assert [s["key"] for s in t["steps"]] == ["pending", "preparing", "ready", "completed"]
    assert client.get("/api/track/ZZZZZZZZ", headers=ANON).status_code == 404
    assert client.get(f"/api/track/{o['id']}", headers=ANON).status_code == 404   # numeric id does not work


def test_delay_is_reported_not_hidden(env):
    client, Session = env
    o = place(client)
    with Session() as db:
        order = db.get(Order, o["id"])
        order.created_at = datetime.utcnow() - timedelta(minutes=o["eta_minutes"] + 6)
        db.commit()
    t = client.get(f"/api/track/{o['tracking_code']}", headers=ANON).json()
    assert t["state"] == "delayed" and t["delay_minutes"] >= 6 and t["remaining_seconds"] == 0
    assert "longer than" in t["message"]


def test_status_flow_records_events_and_ready_state(env):
    client, Session = env
    o = place(client)
    for status in ("preparing", "ready"):
        assert client.patch(f"/api/kitchen/orders/{o['id']}/status", json={"status": status}, headers=KITCHEN).status_code == 200
    t = client.get(f"/api/track/{o['tracking_code']}", headers=ANON).json()
    assert t["state"] == "ready" and t["remaining_seconds"] is None and t["can_rate"] is True
    with Session() as db:
        assert [e.status for e in db.query(OrderStatusEvent).order_by(OrderStatusEvent.id)] == ["pending", "preparing", "ready"]


def test_orders_ahead_counts_earlier_active_orders(env):
    client, _ = env
    place(client); place(client)
    third = place(client)
    assert client.get(f"/api/track/{third['tracking_code']}", headers=ANON).json()["orders_ahead"] == 2


def test_guest_can_cancel_only_while_pending(env):
    client, _ = env
    a, b = place(client), place(client)
    assert client.patch(f"/api/track/{a['tracking_code']}/cancel", headers=ANON).json()["status"] == "cancelled"
    client.patch(f"/api/kitchen/orders/{b['id']}/status", json={"status": "preparing"}, headers=KITCHEN)
    assert client.patch(f"/api/track/{b['tracking_code']}/cancel", headers=ANON).status_code == 409


# ---------------------------------------------------------------- stock
def test_stock_decrements_blocks_oversell_and_restores_on_cancel(env):
    client, Session = env
    assert client.patch("/api/owner/menu/1/stock", json={"stock_quantity": 3}, headers=OWNER).status_code == 200
    over = client.post("/api/orders", json={"customer_name": "Ravi", "items": [{"menu_item_id": 1, "quantity": 4}]}, headers=ANON)
    assert over.status_code == 409 and "Only 3" in over.json()["detail"]
    o = place(client, qty=3)
    with Session() as db:
        item = db.get(MenuItem, 1)
        assert item.stock_quantity == 0 and item.available is False        # sold out automatically
    assert client.post("/api/orders", json={"customer_name": "Ravi", "items": [{"menu_item_id": 1, "quantity": 1}]}, headers=ANON).status_code == 409
    client.patch(f"/api/track/{o['tracking_code']}/cancel", headers=ANON)
    with Session() as db:
        item = db.get(MenuItem, 1)
        assert item.stock_quantity == 3 and item.available is True         # restored


def test_sold_out_dish_not_recommended(env):
    client, _ = env
    client.patch("/api/owner/menu/1/stock", json={"stock_quantity": 0}, headers=OWNER)
    r = client.post("/api/agents/menu/recommend", json={"limit": 20}, headers=ANON).json()
    assert 1 not in [i["id"] for i in r["recommendations"]]


def test_inventory_endpoint_and_staff_only_agent(env):
    client, _ = env
    client.patch("/api/owner/menu/2/stock", json={"stock_quantity": 2}, headers=OWNER)
    inv = client.get("/api/owner/inventory", headers=OWNER).json()
    assert inv["low_stock"][0]["id"] == 2
    cust = client.post("/api/chat", json={"session_id": "inv-session-01", "message": "inventory check"}, headers=ANON).json()
    assert "staff only" in cust["reply"]
    staff = client.post("/api/chat", json={"session_id": "inv-session-02", "message": "inventory check"}, headers=OWNER).json()
    assert "running low" in staff["reply"] and any(a["id"] == "inventory" for a in staff["agents_used"])


# ---------------------------------------------------------------- feedback
def test_feedback_rules_and_service_recovery(env):
    client, Session = env
    o = place(client)
    code = o["tracking_code"]
    assert client.post(f"/api/track/{code}/feedback", json={"rating": 5}, headers=ANON).status_code == 409   # not ready yet
    for s in ("preparing", "ready"):
        client.patch(f"/api/kitchen/orders/{o['id']}/status", json={"status": s}, headers=KITCHEN)
    r = client.post(f"/api/track/{code}/feedback", json={"rating": 1, "comment": "Cold food and a very long wait"}, headers=ANON)
    assert r.status_code == 201 and r.json()["sentiment"] == "negative" and "flagged" in r.json()["message"]
    assert client.post(f"/api/track/{code}/feedback", json={"rating": 5}, headers=ANON).status_code == 409   # only once
    assert client.post(f"/api/track/{code}/feedback", json={"rating": 9}, headers=ANON).status_code == 422
    fb = client.get("/api/owner/feedback", headers=OWNER).json()
    assert fb["needs_follow_up"] == 1 and {t["topic"] for t in fb["top_complaints"]} == {"temperature", "wait time"}
    assert client.get("/api/owner/feedback", headers=ANON).status_code == 401
    client.patch(f"/api/owner/feedback/{fb['recent'][0]['id']}/resolve", headers=OWNER)
    assert client.get("/api/owner/feedback", headers=OWNER).json()["needs_follow_up"] == 0


# ---------------------------------------------------------------- kitchen board
def test_kitchen_board_contents_and_auth(env):
    client, _ = env
    o = place(client, order_type="dine_in", table_number="7", notes="extra crispy")
    assert client.get("/api/kitchen/board", headers=ANON).status_code == 401
    board = client.get("/api/kitchen/board", headers=KITCHEN).json()
    card = board["orders"][0]
    assert card["id"] == o["id"] and card["table_number"] == "7" and card["notes"] == "extra crispy"
    assert card["items"][0]["name"] and card["late"] is False and "level" in board["load"]


# ---------------------------------------------------------------- chat: details, reorder, tracking, feedback
class Chat:
    def __init__(self, client, headers=ANON, sid="v3-session-0001"):
        self.client, self.headers, self.sid = client, headers, sid

    def say(self, m):
        return self.client.post("/api/chat", json={"session_id": self.sid, "message": m}, headers=self.headers).json()


def _order_via_chat(c, extra=()):
    c.say("show vegetarian mains"); c.say("add the first one")
    for m in extra:
        c.say(m)
    c.say("place my order"); c.say("Asha")
    return c.say("yes")


def test_chat_order_carries_type_table_note_and_gives_tracking_code(env):
    client, Session = env
    c = Chat(client)
    r = _order_via_chat(c, ["dine in table 4", "note: no coriander please"])
    assert r["order"]["tracking_code"] and r["order"]["eta_minutes"] >= 5
    with Session() as db:
        o = db.query(Order).one()
        assert (o.order_type, o.table_number, o.notes) == ("dine_in", "4", "no coriander please")


def test_chat_tracking_agent_reports_minutes_left_and_feedback_flow(env):
    client, Session = env
    c = Chat(client)
    _order_via_chat(c)
    r = c.say("how long will my order take?")
    assert r["intent"] == "order_status" and r["tracking"]["remaining_seconds"] > 0
    assert [a["id"] for a in r["agents_used"]] == ["supervisor", "tracking"]
    assert "once it is ready" in c.say("rate 5 stars")["reply"]
    with Session() as db:
        o = db.query(Order).one(); set_status(db, o, "preparing"); set_status(db, o, "ready"); db.commit()
    r = c.say("rate 2 stars, the food was cold")
    assert "flagged" in r["reply"]
    with Session() as db:
        assert db.query(Feedback).one().topics == ["temperature"]


def test_reorder_and_stock_aware_reorder(env):
    client, _ = env
    c = Chat(client)
    _order_via_chat(c)
    r = c.say("order the same again")
    assert r["cart"]["total_items"] == 1
    dish_id = r["cart"]["lines"][0]["menu_item_id"]
    c.say("clear my cart")
    client.patch(f"/api/owner/menu/{dish_id}/stock", json={"stock_quantity": 0}, headers=OWNER)
    r = c.say("order the same again")
    assert "unavailable" in r["reply"] and r["cart"]["total_items"] == 0


def test_note_with_the_word_no_is_not_treated_as_declining(env):
    client, _ = env
    c = Chat(client)
    c.say("show vegetarian mains"); c.say("add the first one")
    r = c.say("note: no coriander please")
    assert r["intent"] == "add_note" and "no coriander" in r["reply"]


def test_cancel_in_chat_restores_stock(env):
    client, Session = env
    client.patch("/api/owner/menu/1/stock", json={"stock_quantity": 5}, headers=OWNER)
    c = Chat(client)
    c.say("show vegetarian mains"); c.say("add the first one")
    with Session() as db:
        first = c.say("my cart")["cart"]["lines"][0]["menu_item_id"]
        client.patch(f"/api/owner/menu/{first}/stock", json={"stock_quantity": 5}, headers=OWNER)
    c.say("place my order"); c.say("Asha"); c.say("yes")
    with Session() as db:
        assert db.get(MenuItem, first).stock_quantity == 4
    c.say("cancel my order"); c.say("yes")
    with Session() as db:
        assert db.get(MenuItem, first).stock_quantity == 5


# ---------------------------------------------------------------- demo data + insights
def test_demo_seeder_labels_data_and_unlocks_honest_insights(env):
    client, Session = env
    import seed_demo
    with Session() as db:
        made = seed_demo.seed(db, days=14, count=200)
    assert made > 120
    ins = client.get("/api/owner/insights", headers=OWNER).json()
    with Session() as db:
        non_cancelled_demo = db.query(Order).filter(Order.is_demo.is_(True), Order.status != "cancelled").count()
    assert ins["data_sufficiency"]["sufficient"] and ins["data_sufficiency"]["demo_orders"] == non_cancelled_demo
    assert ins["insights"][0]["type"] == "demo_data" and "DEMO" in ins["insights"][0]["text"]
    assert ins["forecast"]["available"] is True and "naive baseline" in ins["forecast"]["method"]
    assert ins["operations"]["avg_minutes_to_ready"] and ins["feedback"]["count"] > 0
    with Session() as db:
        assert seed_demo.clear(db) == made
        assert db.query(Order).count() == 0 and db.query(Feedback).count() == 0


def test_stale_orders_do_not_inflate_wait_estimates(env):
    client, Session = env
    for _ in range(6):
        place(client, qty=5)
    fresh = client.get("/api/kitchen/load", headers=KITCHEN).json()
    with Session() as db:
        for o in db.query(Order).all():
            o.created_at = datetime.utcnow() - timedelta(hours=30)
        db.commit()
    after = client.get("/api/kitchen/load", headers=KITCHEN).json()
    assert after["stale_orders"] == 6 and after["active_orders"] == 0 and after["estimated_wait_minutes"] == 0
    assert fresh["estimated_wait_minutes"] > 0
    board = client.get("/api/kitchen/board", headers=KITCHEN).json()
    assert all(c["stale"] for c in board["orders"])           # still visible so staff can clear them
    assert place(client)["eta_minutes"] <= 8                   # a new order gets a sane promise
