"""Owner menu management: add / edit / archive / restore dishes and role separation."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from auth import create_token
from database import Base, get_db
from init_db import initialize_database, load_demo_menu
from main import app
from models import MenuItem

ANON = {"Authorization": ""}
OWNER = {"Authorization": f"Bearer {create_token('owner')}"}
KITCHEN = {"Authorization": f"Bearer {create_token('kitchen')}"}
NEW = {"name": "Butter Chicken Bowl", "price": 289, "category": "Bowls", "description": "Creamy tomato gravy with grilled chicken.",
       "ingredients": ["chicken", "tomato", "cream", "rice"], "dietary_tags": ["non-vegetarian"], "spice_level": "medium"}


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


def test_only_the_owner_can_manage_the_menu(env):
    client, _ = env
    for method, path in [("get", "/api/owner/menu"), ("post", "/api/owner/menu"), ("patch", "/api/owner/menu/1"), ("delete", "/api/owner/menu/1")]:
        assert getattr(client, method)(path, headers=ANON, **({"json": NEW} if method in ("post", "patch") else {})).status_code == 401
        assert getattr(client, method)(path, headers=KITCHEN, **({"json": NEW} if method in ("post", "patch") else {})).status_code == 403


def test_new_dish_reaches_guests_the_chat_agents_and_checkout(env):
    client, _ = env
    r = client.post("/api/owner/menu", json=NEW, headers=OWNER)
    assert r.status_code == 201
    dish = r.json()
    assert dish["spice_level"] == "Medium" and dish["image"] == "data/placeholder.svg" and dish["available"] and not dish["archived"]
    assert dish["id"] not in range(1, 29)                                              # a genuinely new row
    assert dish["id"] in [m["id"] for m in client.get("/api/menu", headers=ANON).json()]   # guests see it
    chat = client.post("/api/chat", json={"session_id": "menu-adm-0001", "message": "add butter chicken bowl"}, headers=ANON).json()
    assert chat["cart"]["lines"][0]["name"] == "Butter Chicken Bowl"                       # the agents know it
    order = client.post("/api/orders", json={"customer_name": "Ravi", "items": [{"menu_item_id": dish["id"], "quantity": 2}]}, headers=ANON)
    assert order.status_code == 201 and order.json()["total_amount"] == 578                # priced by the backend


@pytest.mark.parametrize("patch,expected", [
    ({"price": 0}, 422), ({"price": -5}, 422), ({"name": "A"}, 422), ({"spice_level": "Nuclear"}, 422),
    ({"image": "javascript:alert(1)"}, 422), ({"image": "ftp://x/y.png"}, 422), ({"dietary_tags": ["ok", "Bad<Tag>"]}, 422),
    ({"ingredients": ["x" * 41]}, 422), ({"dietary_tags": [f"t{i}" for i in range(9)]}, 422),
])
def test_invalid_dishes_are_rejected(env, patch, expected):
    client, _ = env
    assert client.post("/api/owner/menu", json={**NEW, **patch}, headers=OWNER).status_code == expected


def test_duplicate_names_are_rejected_case_insensitively(env):
    client, _ = env
    client.post("/api/owner/menu", json=NEW, headers=OWNER)
    assert client.post("/api/owner/menu", json={**NEW, "name": "butter chicken BOWL"}, headers=OWNER).status_code == 409
    first = client.get("/api/menu", headers=ANON).json()[0]
    assert client.patch(f"/api/owner/menu/{first['id']}", json={"name": "BUTTER chicken bowl"}, headers=OWNER).status_code == 409


def test_editing_a_dish_changes_what_guests_and_orders_see(env):
    client, _ = env
    r = client.patch("/api/owner/menu/1", json={"price": 999, "description": "Now even better", "dietary_tags": ["Vegan", "gluten-free"]}, headers=OWNER)
    assert r.status_code == 200 and r.json()["price"] == 999 and r.json()["dietary_tags"] == ["vegan", "gluten-free"]
    assert next(m for m in client.get("/api/menu", headers=ANON).json() if m["id"] == 1)["price"] == 999
    o = client.post("/api/orders", json={"customer_name": "Ravi", "items": [{"menu_item_id": 1, "quantity": 1}]}, headers=ANON).json()
    assert o["total_amount"] == 999
    assert client.patch("/api/owner/menu/1", json={"price": None}, headers=OWNER).status_code == 422
    assert client.patch("/api/owner/menu/9999", json={"price": 5}, headers=OWNER).status_code == 404


def test_archive_hides_everywhere_but_keeps_history_and_can_be_restored(env):
    client, _ = env
    o = client.post("/api/orders", json={"customer_name": "Ravi", "items": [{"menu_item_id": 1, "quantity": 1}]}, headers=ANON).json()
    assert client.delete("/api/owner/menu/1", headers=OWNER).status_code == 200
    assert 1 not in [m["id"] for m in client.get("/api/menu", headers=ANON).json()]
    assert client.get("/api/menu/1", headers=ANON).status_code == 404
    assert client.post("/api/orders", json={"customer_name": "Ravi", "items": [{"menu_item_id": 1, "quantity": 1}]}, headers=ANON).status_code == 409
    assert 1 in [m["id"] for m in client.get("/api/owner/menu", headers=OWNER).json()]              # owner still sees it
    assert client.get(f"/api/track/{o['tracking_code']}", headers=ANON).json()["items"][0]["name"]  # old order intact
    assert client.patch("/api/owner/menu/1", json={"available": True}, headers=OWNER).status_code == 409
    restored = client.post("/api/owner/menu/1/restore", headers=OWNER).json()
    assert restored["available"] and not restored["archived"] and 1 in [m["id"] for m in client.get("/api/menu", headers=ANON).json()]


def test_stock_zero_makes_new_dish_unavailable(env):
    client, _ = env
    d = client.post("/api/owner/menu", json={**NEW, "stock_quantity": 0}, headers=OWNER).json()
    assert d["available"] is False
    assert client.patch(f"/api/owner/menu/{d['id']}", json={"stock_quantity": 5}, headers=OWNER).json()["available"] is True


def test_init_db_does_not_overwrite_owner_edits(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    import init_db
    monkeypatch.setattr(init_db, "engine", engine)
    monkeypatch.setattr(init_db, "SessionLocal", Session)
    initialize_database()
    with Session() as db:
        db.get(MenuItem, 1).price = 12345
        db.commit()
    initialize_database()                         # a normal re-run must keep the owner's price
    with Session() as db:
        assert db.get(MenuItem, 1).price == 12345
    initialize_database(reset_menu=True)          # explicit reset restores the demo value
    with Session() as db:
        assert db.get(MenuItem, 1).price != 12345
