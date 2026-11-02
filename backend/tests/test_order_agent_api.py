
from fastapi.testclient import TestClient

from main import app


client = TestClient(app)


def test_order_preview_returns_successful_response():
    response = client.post(
        "/api/agents/orders/preview",
        json={
            "customer_name": "Test Customer",
            "items": [
                {
                    "menu_item_id": 1,
                    "quantity": 2,
                }
            ],
        },
    )

    assert response.status_code == 200

    data = response.json()

    assert data["customer_name"] == "Test Customer"
    assert data["total_items"] == 2
    assert data["total_amount"] > 0
    assert data["requires_confirmation"] is True
    assert len(data["items"]) == 1


def test_order_preview_rejects_missing_menu_item():
    response = client.post(
        "/api/agents/orders/preview",
        json={
            "customer_name": "Test Customer",
            "items": [
                {
                    "menu_item_id": 999999,
                    "quantity": 1,
                }
            ],
        },
    )

    assert response.status_code == 404


def test_order_preview_rejects_invalid_quantity():
    response = client.post(
        "/api/agents/orders/preview",
        json={
            "customer_name": "Test Customer",
            "items": [
                {
                    "menu_item_id": 1,
                    "quantity": 0,
                }
            ],
        },
    )

    assert response.status_code == 422


def test_order_preview_rejects_empty_items():
    response = client.post(
        "/api/agents/orders/preview",
        json={
            "customer_name": "Test Customer",
            "items": [],
        },
    )

    assert response.status_code == 422

