
from database import SessionLocal
from agents.menu_agent import recommend_menu_items


def test_menu_agent_with_real_database():
    db = SessionLocal()

    try:
        # Test 1: Recommend available dishes.
        recommendations = recommend_menu_items(db)

        assert isinstance(recommendations, list)
        assert all(item.available for item in recommendations)
        assert len(recommendations) <= 5

        print("\nAvailable dish recommendations:")
        for item in recommendations:
            print(f"- {item.name}: {item.price}")

        # Test 2: Respect the budget.
        budget = 200
        budget_recommendations = recommend_menu_items(
            db,
            budget=budget,
        )

        assert all(
            item.price <= budget
            for item in budget_recommendations
        )

        # Test 3: Respect the category filter.
        categories = recommend_menu_items(
            db,
            category="main course",
        )

        assert all(
            item.category.lower() == "main course"
            for item in categories
        )

        # Test 4: Respect the result limit.
        limited_recommendations = recommend_menu_items(
            db,
            limit=2,
        )

        assert len(limited_recommendations) <= 2

    finally:
        db.close()

