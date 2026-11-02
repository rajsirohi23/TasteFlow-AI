
import pytest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import Base
from models import MenuItem
from order_schemas import OrderCreate, OrderItemCreate
from agents.order_agent import prepare_order_preview


@pytest.fixture
def db():
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

    session = TestingSession()

    session.add_all([
        MenuItem(
            name="Paneer Bowl",
            price=180,
            category="Bowls",
            dietary_tags=["vegetarian"],
            ingredients=["paneer", "rice"],
            description="A paneer bowl with rice and fresh vegetables.",
            spice_level="Mild",
            available=True,
            image="paneer-bowl.jpg",
        ),
        MenuItem(
            name="Unavailable Dish",
            price=250,
            category="Main Course",
            dietary_tags=["vegetarian"],
            ingredients=["vegetables"],
            description="A temporarily unavailable test dish.",
            spice_level="Mild",
            available=False,
            image="unavailable.jpg",
        ),
    ])
    session.commit()

    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_order_preview_calculates_correct_total(db):
    order_data = OrderCreate(
        customer_name="Test Customer",
        items=[
            OrderItemCreate(menu_item_id=1, quantity=2),
        ],
    )

    preview = prepare_order_preview(db, order_data)

    assert preview["customer_name"] == "Test Customer"
    assert preview["total_items"] == 2
    assert preview["total_amount"] == 360
    assert preview["items"][0]["unit_price"] == 180
    assert preview["items"][0]["subtotal"] == 360
    assert preview["requires_confirmation"] is True


def test_order_preview_uses_database_price(db):
    order_data = OrderCreate(
        customer_name="Test Customer",
        items=[
            OrderItemCreate(menu_item_id=1, quantity=3),
        ],
    )

    preview = prepare_order_preview(db, order_data)

    assert preview["total_amount"] == 540


def test_order_preview_rejects_unavailable_dish(db):
    order_data = OrderCreate(
        customer_name="Test Customer",
        items=[
            OrderItemCreate(menu_item_id=2, quantity=1),
        ],
    )

    with pytest.raises(ValueError, match="unavailable"):
        prepare_order_preview(db, order_data)


def test_order_preview_rejects_missing_dish(db):
    order_data = OrderCreate(
        customer_name="Test Customer",
        items=[
            OrderItemCreate(menu_item_id=9999, quantity=1),
        ],
    )

    with pytest.raises(ValueError, match="not found"):
        prepare_order_preview(db, order_data)

