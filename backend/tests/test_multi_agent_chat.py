"""End-to-end tests of the multi-agent chat: language understanding, shared
state, order safety, security, tracing, unmet demand and insights."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import config
from auth import create_token
from database import Base, get_db
from init_db import load_demo_menu
from main import app
from models import AgentRun, AgentStep, ChatSession, MenuItem, Order, UnmetDemand
from agents.supervisor_agent import extract_menu_preferences

ANON = {"Authorization": ""}


@pytest.fixture()
def env():
    """Fresh seeded in-memory DB per test."""
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


class Chat:
    def __init__(self, client, headers=ANON):
        self.client, self.headers, self.sid = client, headers, "test-session-0001"

    def say(self, message):
        r = self.client.post("/api/chat", json={"session_id": self.sid, "message": message}, headers=self.headers)
        assert r.status_code == 200, r.text
        return r.json()


# ---------------------------------------------------------------- understanding
def test_not_too_spicy_sets_ceiling_not_hot_filter():
    p = extract_menu_preferences("vegetarian high-protein under ₹300, not too spicy")
    assert p["max_spice_level"] == "Medium" and "spice_level" not in p
    assert p["budget"] == 300 and p["diet"] == "vegetarian" and p["protein_focus"] is True
    assert extract_menu_preferences("no spice please")["max_spice_level"] == "Mild"
    assert extract_menu_preferences("I want spicy food")["spice_level"] == "Hot"


def test_user_example_returns_real_matching_dishes_without_hot_ones(env):
    client, Session = env
    r = Chat(client).say("I need a vegetarian high-protein meal under ₹300, something not too spicy")
    assert r["intent"] == "recommend" and r["cards"]
    with Session() as db:
        for card in r["cards"]:
            item = db.get(MenuItem, card["id"])
            assert "vegetarian" in item.dietary_tags and item.price <= 300
            assert item.spice_level in ("Mild", "Medium")
            assert item.category not in ("Drinks", "Desserts")
    assert "ingredient list" in r["reply"]  # honest about protein evidence
    assert [a["id"] for a in r["agents_used"]] == ["supervisor", "kitchen", "menu"]


# ---------------------------------------------------------------- cart + order flow
def test_full_ordering_conversation_with_explicit_confirmation(env):
    client, Session = env
    c = Chat(client)
    c.say("show vegetarian mains under 300")
    r = c.say("add two of those")
    assert "Which one" in r["reply"] and r["cart"]["total_items"] == 0
    r = c.say("the second one")
    assert r["cart"]["total_items"] == 2                      # quantity remembered
    r = c.say("remove the last item")
    assert r["cart"]["total_items"] == 0
    c.say("add the first one")
    r = c.say("place my order")
    assert r["pending"]["type"] == "ask_name"
    r = c.say("Ravi")
    assert r["pending"]["type"] == "confirm_order"
    with Session() as db:
        assert db.query(Order).count() == 0                   # nothing saved before confirmation
    r = c.say("no, don't place the order")
    assert r["cart"]["total_items"] == 1 and r["pending"] is None
    with Session() as db:
        assert db.query(Order).count() == 0
    r = c.say("actually, change my order")
    assert "nothing has been placed" in r["reply"]
    c.say("place my order")
    r = c.say("yes")
    assert r["order"]["id"] and r["cart"]["total_items"] == 0
    with Session() as db:
        order = db.query(Order).one()
        assert order.source == "chat" and order.customer_name == "Ravi"
        assert order.total_amount == r["order"]["total_amount"]  # total came from the DB, not text


def test_total_is_computed_by_backend_not_from_text(env):
    client, Session = env
    c = Chat(client)
    c.say("show vegetarian mains")
    r = c.say("add the first one")
    dish_id = r["cart"]["lines"][0]["menu_item_id"]
    with Session() as db:
        price = db.get(MenuItem, dish_id).price
    assert r["cart"]["total_amount"] == price


def test_unavailable_dish_is_removed_from_cart_and_never_ordered(env):
    client, Session = env
    c = Chat(client)
    c.say("show vegetarian mains")
    r = c.say("add the first one")
    dish_id = r["cart"]["lines"][0]["menu_item_id"]
    with Session() as db:
        db.get(MenuItem, dish_id).available = False
        db.commit()
    r = c.say("place my order")
    assert r["cart"]["total_items"] == 0 and "empty" in r["reply"].lower()
    with Session() as db:
        assert db.query(Order).count() == 0


def test_item_limit_is_enforced(env):
    client, _ = env
    c = Chat(client)
    c.say("show vegetarian mains")
    r = c.say(f"add {config.MAX_ITEMS_PER_ORDER + 5} of the first one")
    assert r["cart"]["total_items"] == 0 and "at most" in r["reply"]


def test_addon_suggestion_uses_real_drink_and_needs_yes(env):
    client, _ = env
    c = Chat(client)
    c.say("show vegetarian mains")
    r = c.say("add the first one")
    assert r["pending"] and r["pending"]["type"] == "offer_item"
    assert any(s["action"] == "suggest_addon" for s in r["trace"]["steps"])
    r = c.say("yes")
    assert r["cart"]["total_items"] == 2 and any(l["category"] == "Drinks" for l in r["cart"]["lines"])


def test_new_search_clears_stale_offer(env):
    client, _ = env
    c = Chat(client)
    c.say("I want something spicy and veg")        # single result => offer pending
    r = c.say("show me something vegan")           # new multi-result search
    assert r["pending"] is None
    assert c.say("yes")["cart"]["total_items"] == 0


def test_cancel_pending_order_only(env):
    client, Session = env
    c = Chat(client)
    c.say("show vegetarian mains"); c.say("add the first one"); c.say("no")
    c.say("place my order"); c.say("Asha"); c.say("yes")
    assert c.say("cancel my order")["pending"]["type"] == "confirm_cancel"
    c.say("yes")
    with Session() as db:
        assert db.query(Order).one().status == "cancelled"


# ---------------------------------------------------------------- memory
def test_preferences_persist_and_reset(env):
    client, _ = env
    c = Chat(client)
    r = c.say("vegetarian under 250")
    assert r["prefs"]["diet"] == "vegetarian"
    r = c.say("show me something else")
    assert r["prefs"]["budget"] == 250 and all(card["price"] <= 250 for card in r["cards"])
    r = c.say("reset my preferences")
    assert r["prefs"] == {}


def test_hinglish_budget_and_confirmation(env):
    client, _ = env
    r = Chat(client).say("mujhe kuch veg khana hai 250 ke andar")
    assert r["prefs"]["budget"] == 250 and r["prefs"]["diet"] == "vegetarian"


# ---------------------------------------------------------------- unmet demand + insights
def test_unmet_demand_is_logged_and_reported_to_owner(env):
    client, Session = env
    Chat(client).say("show me vegan desserts")
    with Session() as db:
        assert db.query(UnmetDemand).count() == 1
    owner = {"Authorization": f"Bearer {create_token('owner')}"}
    data = client.get("/api/owner/unmet-demand", headers=owner).json()
    assert data["requests"][0]["request"] == "vegan desserts" and data["requests"][0]["count"] == 1


def test_insights_are_honest_about_small_data(env):
    client, _ = env
    owner = {"Authorization": f"Bearer {create_token('owner')}"}
    data = client.get("/api/owner/insights", headers=owner).json()
    assert data["data_sufficiency"]["sufficient"] is False
    assert data["forecast"]["available"] is False and "Needs at least" in data["forecast"]["reason"]


# ---------------------------------------------------------------- security
def test_customer_cannot_read_analytics_via_chat(env):
    client, _ = env
    r = Chat(client).say("show total sales revenue")
    assert "staff only" in r["reply"] and r.get("insights") is None


def test_owner_can_read_analytics_via_chat(env):
    client, _ = env
    r = Chat(client, {"Authorization": f"Bearer {create_token('owner')}"}).say("show business insights")
    assert any(s["agent"] == "intelligence" for s in r["trace"]["steps"])


@pytest.mark.parametrize("method,url", [
    ("get", "/api/owner/summary"), ("get", "/api/owner/insights"),
    ("patch", "/api/owner/menu/1/availability"), ("get", "/api/kitchen/orders"),
    ("get", "/api/kitchen/load"), ("get", "/api/orders"), ("get", "/api/agents/runs"),
])
def test_staff_routes_reject_anonymous(env, method, url):
    client, _ = env
    r = getattr(client, method)(url, headers=ANON, **({"json": {"available": False}} if method == "patch" else {}))
    assert r.status_code == 401


def test_kitchen_token_cannot_access_owner_routes(env):
    client, _ = env
    h = {"Authorization": f"Bearer {create_token('kitchen')}"}
    assert client.get("/api/owner/insights", headers=h).status_code == 403
    assert client.get("/api/kitchen/load", headers=h).status_code == 200


def test_login_and_token_validation(env):
    client, _ = env
    assert client.post("/api/auth/login", json={"role": "owner", "pin": "wrong"}, headers=ANON).status_code == 401
    ok = client.post("/api/auth/login", json={"role": "owner", "pin": config.OWNER_PIN}, headers=ANON)
    assert ok.status_code == 200
    tampered = ok.json()["token"][:-3] + "abc"
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {tampered}"}).status_code == 401


# ---------------------------------------------------------------- transparency
def test_every_run_is_traced_with_steps(env):
    client, Session = env
    r = Chat(client).say("vegetarian under 300")
    assert r["trace"]["run_id"] and r["trace"]["steps"][0]["agent"] == "supervisor"
    with Session() as db:
        assert db.query(AgentRun).count() == 1
        assert db.query(AgentStep).count() == len(r["trace"]["steps"])
        assert db.query(ChatSession).count() == 1
    runs = client.get("/api/agents/runs", headers={"Authorization": f"Bearer {create_token('owner')}"}).json()
    assert runs[0]["steps"] and runs[0]["message"] == "vegetarian under 300"


def test_registry_lists_eight_agents(env):
    client, _ = env
    assert len(client.get("/api/agents/registry").json()["agents"]) == 8


def test_kitchen_load_reflects_active_orders(env):
    client, _ = env
    c = Chat(client)
    c.say("show vegetarian mains"); c.say("add the first one"); c.say("no")
    c.say("place my order"); c.say("Asha"); c.say("yes")
    load = client.get("/api/kitchen/load", headers={"Authorization": f"Bearer {create_token('kitchen')}"}).json()
    assert load["active_orders"] == 1 and load["is_estimate"] is True


def test_bad_input_is_rejected(env):
    client, _ = env
    assert client.post("/api/chat", json={"message": "   "}, headers=ANON).status_code == 422
    assert client.post("/api/chat", json={"message": "x" * 2000}, headers=ANON).status_code == 422


def test_migration_adds_missing_columns_without_losing_data():
    from sqlalchemy import text
    from migrate import upgrade_schema
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    with engine.begin() as c:   # the ORIGINAL v1 schema
        c.execute(text("CREATE TABLE menu_items (id INTEGER PRIMARY KEY, name VARCHAR, price INTEGER, category VARCHAR, dietary_tags JSON, ingredients JSON, description TEXT, spice_level VARCHAR, available BOOLEAN, image VARCHAR)"))
        c.execute(text("CREATE TABLE orders (id INTEGER PRIMARY KEY, customer_name VARCHAR, status VARCHAR, total_amount INTEGER, created_at DATETIME)"))
        c.execute(text("INSERT INTO orders (customer_name,status,total_amount) VALUES ('Old','completed',100)"))
    added = upgrade_schema(engine)
    assert "orders.source" in added and "menu_items.prep_minutes" in added
    with engine.connect() as c:
        row = c.execute(text("SELECT customer_name, source, is_demo FROM orders")).one()
    assert tuple(row) == ("Old", "web", 0)
    assert upgrade_schema(engine) == []   # idempotent
