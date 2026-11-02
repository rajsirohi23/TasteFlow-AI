
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import Base
from models import MenuItem, Order, OrderItem
from agents.menu_agent import recommend_menu_items


def create_test_db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    Base.metadata.create_all(bind=engine)

    TestingSession = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
    )

    return engine, TestingSession()


def test_cancelled_orders_do_not_increase_popularity():
    engine, db = create_test_db()

    try:
        popular_dish = MenuItem(
            name="Popular Dish",
            price=100,
            category="Main Course",
            dietary_tags=["vegetarian"],
            ingredients=["rice"],
            description="A popular vegetarian dish.",
            spice_level="Mild",
            available=True,
            image="popular.jpg",
        )

        other_dish = MenuItem(
            name="Other Dish",
            price=100,
            category="Main Course",
            dietary_tags=["vegetarian"],
            ingredients=["rice"],
            description="Another vegetarian dish.",
            spice_level="Mild",
            available=True,
            image="other.jpg",
        )

        db.add_all([popular_dish, other_dish])
        db.commit()

        db.add_all([
            Order(
                customer_name="Test Customer",
                status="completed",
                total_amount=300,
            ),
            Order(
                customer_name="Test Customer",
                status="cancelled",
                total_amount=900,
            ),
        ])
        db.commit()

        completed_order = (
            db.query(Order)
            .filter(Order.status == "completed")
            .one()
        )

        cancelled_order = (
            db.query(Order)
            .filter(Order.status == "cancelled")
            .one()
        )

        db.add_all([
            OrderItem(
                order_id=completed_order.id,
                menu_item_id=popular_dish.id,
                quantity=3,
                unit_price=100,
            ),
            OrderItem(
                order_id=cancelled_order.id,
                menu_item_id=other_dish.id,
                quantity=9,
                unit_price=100,
            ),
        ])
        db.commit()

        recommendations = recommend_menu_items(
            db=db,
            limit=2,
        )

        # The completed order gives Popular Dish a popularity bonus.
        assert recommendations[0].id == popular_dish.id

        # The nine cancelled units must not make Other Dish rank first.
        assert recommendations[1].id == other_dish.id

    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()
