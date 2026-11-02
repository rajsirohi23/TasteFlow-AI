
from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


def test_menu_request_routes_to_menu_agent():
    response = client.post(
        "/api/agents/supervisor/route",
        json={"message": "Recommend vegetarian dishes under ₹200"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["selected_agent"] == "menu"
    assert data["intent"] == "menu_recommendation"


def test_order_request_routes_to_order_agent():
    response = client.post(
        "/api/agents/supervisor/route",
        json={"message": "I want to preview my order"},
    )

    assert response.status_code == 200
    assert response.json()["selected_agent"] == "order"


def test_analytics_request_routes_to_analytics_agent():
    response = client.post(
        "/api/agents/supervisor/route",
        json={"message": "Show me restaurant revenue"},
    )

    assert response.status_code == 200
    assert response.json()["selected_agent"] == "analytics"


def test_general_request_uses_general_route():
    response = client.post(
        "/api/agents/supervisor/route",
        json={"message": "Hello, how are you?"},
    )

    assert response.status_code == 200
    assert response.json()["selected_agent"] == "general"


def test_missing_message_returns_validation_error():
    response = client.post(
        "/api/agents/supervisor/route",
        json={},
    )

    assert response.status_code == 422


def test_empty_message_returns_validation_error():
    response = client.post(
        "/api/agents/supervisor/route",
        json={"message": ""},
    )

    assert response.status_code == 422







def test_whitespace_only_message_returns_validation_error():
    response = client.post(
        "/api/agents/supervisor/route",
        json={"message": "     "},
    )

    assert response.status_code == 422


def test_message_over_1000_characters_returns_validation_error():
    response = client.post(
        "/api/agents/supervisor/route",
        json={"message": "a" * 1001},
    )

    assert response.status_code == 422

