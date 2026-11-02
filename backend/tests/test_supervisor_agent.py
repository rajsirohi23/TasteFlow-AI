
from agents.supervisor_agent import route_customer_request


def test_menu_request_routes_to_menu_agent():
    result = route_customer_request(
        "Recommend vegetarian dishes under ₹200"
    )

    assert result["agent"] == "menu"
    assert result["intent"] == "menu_recommendation"


def test_order_request_routes_to_order_agent():
    result = route_customer_request("I want to preview my order")

    assert result["agent"] == "order"
    assert result["intent"] == "order_request"


def test_analytics_request_routes_to_analytics_agent():
    result = route_customer_request("Show me restaurant revenue")

    assert result["agent"] == "analytics"
    assert result["intent"] == "analytics_request"


def test_general_question_uses_general_route():
    result = route_customer_request("Hello, how are you?")

    assert result["agent"] == "general"
    assert result["intent"] == "general_question"


def test_empty_request_is_handled():
    result = route_customer_request("   ")

    assert result["agent"] == "general"
    assert result["intent"] == "empty_request"
