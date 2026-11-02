
from fastapi.testclient import TestClient

from main import app


client = TestClient(app)


def test_menu_agent_returns_successful_response():
    response = client.post(
        "/api/agents/menu/recommend",
        json={},
    )

    assert response.status_code == 200

    data = response.json()

    assert "count" in data
    assert "recommendations" in data
    assert data["count"] == len(data["recommendations"])


def test_menu_agent_respects_budget():
    budget = 200

    response = client.post(
        "/api/agents/menu/recommend",
        json={"budget": budget, "limit": 5},
    )

    assert response.status_code == 200

    for item in response.json()["recommendations"]:
        assert item["price"] <= budget


def test_menu_agent_respects_diet():
    diet = "vegetarian"

    response = client.post(
        "/api/agents/menu/recommend",
        json={"diet": diet, "limit": 5},
    )

    assert response.status_code == 200

    for item in response.json()["recommendations"]:
        tags = [tag.lower() for tag in item["dietary_tags"]]
        assert diet in tags


def test_menu_agent_respects_result_limit():
    limit = 3

    response = client.post(
        "/api/agents/menu/recommend",
        json={"limit": limit},
    )

    assert response.status_code == 200
    assert len(response.json()["recommendations"]) <= limit


def test_menu_agent_rejects_invalid_limit():
    response = client.post(
        "/api/agents/menu/recommend",
        json={"limit": 0},
    )

    assert response.status_code == 422

