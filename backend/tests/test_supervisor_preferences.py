
from agents.supervisor_agent import extract_menu_preferences


def test_extracts_budget_and_diet():
    result = extract_menu_preferences(
        "Recommend vegetarian dishes under ₹200"
    )

    assert result["budget"] == 200
    assert result["diet"] == "vegetarian"
    assert result["limit"] == 5


def test_extracts_category_and_spice():
    result = extract_menu_preferences(
        "Show me hot desserts"
    )

    assert result["category"] == "Desserts"
    assert result["spice_level"] == "Hot"


def test_message_without_preferences_uses_defaults():
    result = extract_menu_preferences("Recommend something")

    assert result == {"limit": 5}


def test_extracts_non_vegetarian_correctly():
    result = extract_menu_preferences(
        "Recommend non-vegetarian dishes"
    )

    assert result["diet"] == "non-vegetarian"
