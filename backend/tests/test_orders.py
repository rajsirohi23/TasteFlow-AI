
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import Base, get_db
from main import app
from models import MenuItem


@pytest.fixture
def client():
    # Use a separate in-memory database for every test.
    test_engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    TestSessionLocal = sessionmaker(
        bind=test_engine,
        autoflush=False,
        autocommit=False,
    )

    Base.metadata.create_all(bind=test_engine)

    # Seed predictable menu data for testing.
    with TestSessionLocal() as db:
        db.add_all(
            [
                MenuItem(
                    id=1,
                    name="Garden Fresh Bowl",
                    price=249,
                    category="Bowls",
                    dietary_tags=["vegetarian"],
                    ingredients=["lettuce", "tomato"],
                    description="Fresh vegetable bowl",
                    spice_level="Mild",
                    available=True,
                    image="demo-image-1.jpg",
                ),
                MenuItem(
                    id=2,
                    name="Paneer Tikka",
                    price=279,
                    category="Starters",
                    dietary_tags=["vegetarian"],
                    ingredients=["paneer", "spices"],
                    description="Grilled paneer",
                    spice_level="Medium",
                    available=True,
                    image="demo-image-2.jpg",
                ),
                MenuItem(
                    id=8,
                    name="Seasonal Vegetable Stir-Fry",
                    price=219,
                    category="Bowls",
                    dietary_tags=["vegan", "vegetarian"],
                    ingredients=["seasonal vegetables"],
                    description="Seasonal vegetable stir-fry",
                    spice_level="Mild",
                    available=False,
                    image="demo-image-8.jpg",
                ),
            ]
        )
        db.commit()

    def override_get_db():
        db = TestSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=test_engine)
    test_engine.dispose()


def test_create_order_calculates_database_prices(client):
    response = client.post(
        "/api/orders",
        json={
            "customer_name": "Test Customer",
            "items": [
                {"menu_item_id": 1, "quantity": 2},
                {"menu_item_id": 2, "quantity": 1},
            ],
        },
    )

    assert response.status_code == 201

    data = response.json()
    assert data["total_amount"] == 777
    assert data["status"] == "pending"
    assert len(data["items"]) == 2


def test_unavailable_item_is_rejected(client):
    response = client.post(
        "/api/orders",
        json={
            "customer_name": "Test Customer",
            "items": [{"menu_item_id": 8, "quantity": 1}],
        },
    )

    assert response.status_code == 409
    assert client.get("/api/orders").json() == []


def test_missing_order_returns_404(client):
    response = client.get("/api/orders/9999")

    assert response.status_code == 404


def test_orders_can_be_listed_and_retrieved(client):
    created = client.post(
        "/api/orders",
        json={
            "customer_name": "Test Customer",
            "items": [{"menu_item_id": 1, "quantity": 1}],
        },
    )

    assert created.status_code == 201
    order_id = created.json()["id"]

    detail = client.get(f"/api/orders/{order_id}")
    listing = client.get("/api/orders")

    assert detail.status_code == 200
    assert detail.json()["id"] == order_id
    assert len(detail.json()["items"]) == 1
    assert listing.status_code == 200
    assert any(item["id"] == order_id for item in listing.json())


def test_invalid_status_transition_is_rejected(client):
    created = client.post(
        "/api/orders",
        json={
            "customer_name": "Test Customer",
            "items": [{"menu_item_id": 1, "quantity": 1}],
        },
    )
    order_id = created.json()["id"]

    response = client.patch(
        f"/api/orders/{order_id}/status",
        json={"status": "completed"},
    )

    assert response.status_code == 409

    valid_response = client.patch(
        f"/api/orders/{order_id}/status",
        json={"status": "preparing"},
    )

    assert valid_response.status_code == 200
    assert valid_response.json()["status"] == "preparing"


def test_pending_order_can_be_cancelled(client):
    created = client.post(
        "/api/orders",
        json={
            "customer_name": "Test Customer",
            "items": [{"menu_item_id": 1, "quantity": 1}],
        },
    )
    order_id = created.json()["id"]

    response = client.patch(f"/api/orders/{order_id}/cancel")

    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"


def test_preparing_order_cannot_be_cancelled(client):
    created = client.post(
        "/api/orders",
        json={
            "customer_name": "Test Customer",
            "items": [{"menu_item_id": 1, "quantity": 1}],
        },
    )
    order_id = created.json()["id"]

    client.patch(
        f"/api/orders/{order_id}/status",
        json={"status": "preparing"},
    )

    response = client.patch(f"/api/orders/{order_id}/cancel")

    assert response.status_code == 409



def test_order_history_pagination(client):
    created_ids = []

    for _ in range(3):
        response = client.post(
            "/api/orders",
            json={
                "customer_name": "History Test",
                "items": [{"menu_item_id": 1, "quantity": 1}],
            },
        )
        assert response.status_code == 201
        created_ids.append(response.json()["id"])

    first_page = client.get("/api/orders?limit=2&offset=0")
    second_page = client.get("/api/orders?limit=2&offset=2")

    assert first_page.status_code == 200
    assert second_page.status_code == 200

    first_ids = [order["id"] for order in first_page.json()]
    second_ids = [order["id"] for order in second_page.json()]

    assert len(first_ids) == 2
    assert len(second_ids) == 1
    assert first_ids == created_ids[::-1][:2]
    assert second_ids == created_ids[:1]


def test_invalid_quantity_does_not_create_order(client):
    response = client.post(
        "/api/orders",
        json={
            "customer_name": "Invalid Quantity Test",
            "items": [{"menu_item_id": 1, "quantity": 0}],
        },
    )

    assert response.status_code == 422

    history = client.get("/api/orders")
    assert history.status_code == 200
    assert history.json() == []


def test_mixed_available_and_unavailable_items_create_no_order(client):
    response = client.post(
        "/api/orders",
        json={
            "customer_name": "Mixed Items Test",
            "items": [
                {"menu_item_id": 1, "quantity": 1},
                {"menu_item_id": 8, "quantity": 1},
            ],
        },
    )

    assert response.status_code == 409

    # The available dish must not be saved as a partial order.
    history = client.get("/api/orders")
    assert history.status_code == 200
    assert history.json() == []





def test_kitchen_queue_includes_only_active_orders(client):
    def create_test_order(name):
        response = client.post(
            "/api/orders",
            json={
                "customer_name": name,
                "items": [{"menu_item_id": 1, "quantity": 1}],
            },
        )
        assert response.status_code == 201
        return response.json()["id"]

    # Create one order for each workflow status.
    pending_id = create_test_order("Pending Customer")

    preparing_id = create_test_order("Preparing Customer")
    response = client.patch(
        f"/api/orders/{preparing_id}/status",
        json={"status": "preparing"},
    )
    assert response.status_code == 200

    ready_id = create_test_order("Ready Customer")
    client.patch(
        f"/api/orders/{ready_id}/status",
        json={"status": "preparing"},
    )
    response = client.patch(
        f"/api/orders/{ready_id}/status",
        json={"status": "ready"},
    )
    assert response.status_code == 200

    completed_id = create_test_order("Completed Customer")
    client.patch(
        f"/api/orders/{completed_id}/status",
        json={"status": "preparing"},
    )
    client.patch(
        f"/api/orders/{completed_id}/status",
        json={"status": "ready"},
    )
    response = client.patch(
        f"/api/orders/{completed_id}/status",
        json={"status": "completed"},
    )
    assert response.status_code == 200

    cancelled_id = create_test_order("Cancelled Customer")
    response = client.patch(
        f"/api/orders/{cancelled_id}/cancel"
    )
    assert response.status_code == 200

    response = client.get("/api/kitchen/orders")

    assert response.status_code == 200

    orders = response.json()
    returned_ids = [order["id"] for order in orders]

    assert returned_ids == [pending_id, preparing_id, ready_id]
    assert completed_id not in returned_ids
    assert cancelled_id not in returned_ids


def test_kitchen_queue_pagination(client):
    created_ids = []

    for index in range(3):
        response = client.post(
            "/api/orders",
            json={
                "customer_name": f"Kitchen Customer {index}",
                "items": [{"menu_item_id": 1, "quantity": 1}],
            },
        )

        assert response.status_code == 201
        created_ids.append(response.json()["id"])

    first_page = client.get(
        "/api/kitchen/orders?limit=2&offset=0"
    )
    second_page = client.get(
        "/api/kitchen/orders?limit=2&offset=2"
    )

    assert first_page.status_code == 200
    assert second_page.status_code == 200

    first_ids = [order["id"] for order in first_page.json()]
    second_ids = [order["id"] for order in second_page.json()]

    assert first_ids == created_ids[:2]
    assert second_ids == created_ids[2:]



def test_kitchen_status_endpoint_enforces_transitions(client):
    created = client.post(
        "/api/orders",
        json={
            "customer_name": "Kitchen Status Test",
            "items": [{"menu_item_id": 1, "quantity": 1}],
        },
    )

    assert created.status_code == 201
    order_id = created.json()["id"]

    # Skipping directly from pending to completed must fail.
    invalid = client.patch(
        f"/api/kitchen/orders/{order_id}/status",
        json={"status": "completed"},
    )
    assert invalid.status_code == 409

    # The valid next transition must succeed.
    valid = client.patch(
        f"/api/kitchen/orders/{order_id}/status",
        json={"status": "preparing"},
    )
    assert valid.status_code == 200
    assert valid.json()["status"] == "preparing"




def test_owner_summary_calculates_order_metrics(client):
    def create_order(name, quantity=1):
        response = client.post(
            "/api/orders",
            json={
                "customer_name": name,
                "items": [
                    {"menu_item_id": 1, "quantity": quantity}
                ],
            },
        )
        assert response.status_code == 201
        return response.json()["id"]

    # ₹249 pending order.
    create_order("Pending Owner Test")

    # ₹498 completed order.
    completed_id = create_order("Completed Owner Test", quantity=2)

    response = client.patch(
        f"/api/orders/{completed_id}/status",
        json={"status": "preparing"},
    )
    assert response.status_code == 200

    response = client.patch(
        f"/api/orders/{completed_id}/status",
        json={"status": "ready"},
    )
    assert response.status_code == 200

    response = client.patch(
        f"/api/orders/{completed_id}/status",
        json={"status": "completed"},
    )
    assert response.status_code == 200

    # ₹249 cancelled order.
    cancelled_id = create_order("Cancelled Owner Test")
    response = client.patch(
        f"/api/orders/{cancelled_id}/cancel"
    )
    assert response.status_code == 200

    response = client.get("/api/owner/summary")

    assert response.status_code == 200

    data = response.json()

    assert data["total_orders"] == 3
    assert data["active_orders"] == 1
    assert data["completed_orders"] == 1
    assert data["cancelled_orders"] == 1
    assert data["non_cancelled_order_value"] == 747
    assert data["completed_order_value"] == 498
    assert data["average_completed_order_value"] == 498
    assert data["currency"] == "INR"



def test_owner_popular_dishes_excludes_cancelled_orders(client):
    # Order containing two Garden Fresh Bowls and one Paneer Tikka.
    created = client.post(
        "/api/orders",
        json={
            "customer_name": "Popular Dish Test",
            "items": [
                {"menu_item_id": 1, "quantity": 2},
                {"menu_item_id": 2, "quantity": 1},
            ],
        },
    )
    assert created.status_code == 201

    # A cancelled order must not affect the popularity figures.
    cancelled = client.post(
        "/api/orders",
        json={
            "customer_name": "Cancelled Popular Dish Test",
            "items": [{"menu_item_id": 1, "quantity": 5}],
        },
    )
    assert cancelled.status_code == 201

    cancelled_id = cancelled.json()["id"]
    response = client.patch(
        f"/api/orders/{cancelled_id}/cancel"
    )
    assert response.status_code == 200

    response = client.get("/api/owner/popular-dishes")

    assert response.status_code == 200
    data = response.json()

    assert len(data) == 2
    assert data[0]["menu_item_id"] == 1
    assert data[0]["name"] == "Garden Fresh Bowl"
    assert data[0]["quantity_ordered"] == 2
    assert data[0]["order_count"] == 1
    assert data[0]["recorded_value"] == 498

    assert data[1]["menu_item_id"] == 2
    assert data[1]["quantity_ordered"] == 1
    assert data[1]["order_count"] == 1
    assert data[1]["recorded_value"] == 279






def test_owner_low_demand_excludes_cancelled_orders(client):
    # Garden Fresh Bowl: two units in a valid order.
    created = client.post(
        "/api/orders",
        json={
            "customer_name": "Low Demand Test",
            "items": [
                {"menu_item_id": 1, "quantity": 2},
            ],
        },
    )
    assert created.status_code == 201

    # Five more units, but this order will be cancelled.
    cancelled = client.post(
        "/api/orders",
        json={
            "customer_name": "Cancelled Demand Test",
            "items": [
                {"menu_item_id": 1, "quantity": 5},
            ],
        },
    )
    assert cancelled.status_code == 201

    cancelled_id = cancelled.json()["id"]
    response = client.patch(
        f"/api/orders/{cancelled_id}/cancel"
    )
    assert response.status_code == 200

    response = client.get(
        "/api/owner/low-demand-dishes?threshold=2"
    )

    assert response.status_code == 200
    data = response.json()

    assert data["threshold"] == 2

    dishes = {
        dish["menu_item_id"]: dish
        for dish in data["dishes"]
    }

    # Only the two units from the non-cancelled order count.
    assert dishes[1]["quantity_ordered"] == 2
    assert dishes[1]["order_count"] == 1
    assert dishes[1]["demand_label"] == "low_demand"

    # The seeded menu item with no orders should appear.
    assert dishes[8]["quantity_ordered"] == 0
    assert dishes[8]["order_count"] == 0
    assert dishes[8]["demand_label"] == "never_ordered"




def test_owner_can_update_menu_availability(client):
    # Demo dish 8 starts unavailable.
    response = client.get("/api/menu/8")
    assert response.status_code == 200
    assert response.json()["available"] is False

    # Mark it available.
    response = client.patch(
        "/api/owner/menu/8/availability",
        json={"available": True},
    )

    assert response.status_code == 200
    assert response.json()["available"] is True

    # Verify the change was saved in the test database.
    response = client.get("/api/menu/8")
    assert response.status_code == 200
    assert response.json()["available"] is True

    # Mark it unavailable again.
    response = client.patch(
        "/api/owner/menu/8/availability",
        json={"available": False},
    )

    assert response.status_code == 200
    assert response.json()["available"] is False

    # Nonexistent menu item should return 404.
    response = client.patch(
        "/api/owner/menu/9999/availability",
        json={"available": True},
    )

    assert response.status_code == 404




def test_unavailable_dish_is_hidden_from_available_menu_and_cannot_be_ordered(client):
    # The unavailable dish should still appear in the full menu.
    full_menu = client.get("/api/menu")
    assert full_menu.status_code == 200

    full_menu_ids = [item["id"] for item in full_menu.json()]
    assert 8 in full_menu_ids

    # The available-only menu must exclude unavailable dishes.
    available_menu = client.get("/api/menu?available_only=true")
    assert available_menu.status_code == 200

    available_ids = [item["id"] for item in available_menu.json()]
    assert 8 not in available_ids

    # The owner-facing menu lookup should still show the dish.
    dish = client.get("/api/menu/8")
    assert dish.status_code == 200
    assert dish.json()["available"] is False

    # Customers must not be able to order the unavailable dish.
    order = client.post(
        "/api/orders",
        json={
            "customer_name": "Unavailable Dish Test",
            "items": [
                {"menu_item_id": 8, "quantity": 1}
            ],
        },
    )

    assert order.status_code == 409

    # The failed request must not create an order.
    history = client.get("/api/orders")
    assert history.status_code == 200
    assert history.json() == []



def test_owner_dish_history_excludes_cancelled_orders(client):
    # Create an order with two Garden Fresh Bowls.
    created = client.post(
        "/api/orders",
        json={
            "customer_name": "Dish History Test",
            "items": [{"menu_item_id": 1, "quantity": 2}],
        },
    )
    assert created.status_code == 201

    # Create another order, then cancel it.
    cancelled = client.post(
        "/api/orders",
        json={
            "customer_name": "Cancelled History Test",
            "items": [{"menu_item_id": 1, "quantity": 5}],
        },
    )
    assert cancelled.status_code == 201

    cancelled_id = cancelled.json()["id"]
    cancel_response = client.patch(
        f"/api/orders/{cancelled_id}/cancel"
    )
    assert cancel_response.status_code == 200

    # Read the dish history.
    response = client.get("/api/owner/menu/1/history")

    assert response.status_code == 200
    data = response.json()

    assert data["menu_item_id"] == 1
    assert data["name"] == "Garden Fresh Bowl"
    assert data["quantity_ordered"] == 2
    assert data["order_count"] == 1
    assert data["recorded_value"] == 498
    assert len(data["recent_orders"]) == 1
    assert data["recent_orders"][0]["quantity"] == 2

    # An unknown dish should return 404.
    missing = client.get("/api/owner/menu/9999/history")
    assert missing.status_code == 404



def test_owner_summary_rejects_invalid_date_range(client):
    response = client.get(
        "/api/owner/summary",
        params={
            "start_date": "2026-10-28",
            "end_date": "2026-10-20",
        },
    )

    assert response.status_code == 422


def test_owner_summary_accepts_date_range(client):
    response = client.get(
        "/api/owner/summary",
        params={
            "start_date": "2026-10-20",
            "end_date": "2026-10-28",
        },
    )

    assert response.status_code == 200


def test_popular_dishes_accepts_date_range(client):
    response = client.get(
        "/api/owner/popular-dishes",
        params={
            "start_date": "2026-10-20",
            "end_date": "2026-10-28",
        },
    )

    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_popular_dishes_rejects_invalid_date_range(client):
    response = client.get(
        "/api/owner/popular-dishes",
        params={
            "start_date": "2026-10-28",
            "end_date": "2026-10-20",
        },
    )

    assert response.status_code == 422


def test_owner_dish_history_accepts_date_range(client):
    response = client.get(
        "/api/owner/menu/1/history",
        params={
            "start_date": "2026-10-20",
            "end_date": "2026-10-30",
        },
    )

    assert response.status_code == 200
    data = response.json()

    assert data["menu_item_id"] == 1
    assert "quantity_ordered" in data
    assert "order_count" in data
    assert "recorded_value" in data
    assert "recent_orders" in data


def test_owner_dish_history_rejects_invalid_date_range(client):
    response = client.get(
        "/api/owner/menu/1/history",
        params={
            "start_date": "2026-10-30",
            "end_date": "2026-10-20",
        },
    )

    assert response.status_code == 422
