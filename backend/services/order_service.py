"""Order business rules. The ONLY place that prices, validates and saves orders.

Web checkout, the chat agents and voice all call these functions, so the LLM
can never decide a price, a total, a stock level or whether an order was saved.
"""
import secrets
from collections import defaultdict

from sqlalchemy.orm import Session

import config
from models import MenuItem, Order, OrderItem, OrderStatusEvent
from order_schemas import OrderResponse
from services.kitchen_service import get_kitchen_load

ALLOWED_STATUS_TRANSITIONS = {
    "pending": {"preparing"},
    "preparing": {"ready"},
    "ready": {"completed"},
    "completed": set(),
    "cancelled": set(),
}


def is_valid_status_transition(current_status: str, new_status: str) -> bool:
    """Check whether an order can move to the requested status."""
    if current_status == new_status:
        return True
    return new_status in ALLOWED_STATUS_TRANSITIONS.get(current_status, set())


class OrderError(Exception):
    """A business-rule failure that maps cleanly to an HTTP status."""

    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.message = message


def is_orderable(item: MenuItem) -> bool:
    return bool(item.available) and (item.stock_quantity is None or item.stock_quantity > 0)


def price_lines(db: Session, lines: list[tuple[int, int]]) -> dict:
    """Validate (menu_item_id, quantity) pairs and price them from the DB.

    Raises OrderError(404) for unknown dishes, 409 for unavailable / sold-out /
    insufficient stock, 422 when the order is too large.
    """
    merged: dict[int, int] = defaultdict(int)
    for item_id, quantity in lines:
        merged[item_id] += quantity

    priced, total_amount, total_items = [], 0, 0
    for item_id, quantity in merged.items():
        item = db.get(MenuItem, item_id)
        if item is None:
            raise OrderError(404, f"Menu item {item_id} was not found")
        if not is_orderable(item):
            raise OrderError(409, f"{item.name} is currently unavailable")
        if item.stock_quantity is not None and quantity > item.stock_quantity:
            raise OrderError(409, f"Only {item.stock_quantity} {item.name} left")
        subtotal = item.price * quantity
        priced.append({"menu_item_id": item.id, "name": item.name,
                       "quantity": quantity, "unit_price": item.price,
                       "subtotal": subtotal, "category": item.category})
        total_amount += subtotal
        total_items += quantity

    if total_items > config.MAX_ITEMS_PER_ORDER:
        raise OrderError(
            422, f"An order can contain at most {config.MAX_ITEMS_PER_ORDER} items"
        )
    return {"lines": priced, "total_items": total_items, "total_amount": total_amount}


def _new_tracking_code(db: Session) -> str:
    while True:
        code = secrets.token_hex(4).upper()
        if not db.query(Order.id).filter(Order.tracking_code == code).first():
            return code


def create_order(
    db: Session,
    customer_name: str,
    lines: list[tuple[int, int]],
    source: str = "web",
    session_id: str | None = None,
    is_demo: bool = False,
    order_type: str = "takeaway",
    table_number: str | None = None,
    notes: str | None = None,
) -> Order:
    """Price, validate, reserve stock and save an order in ONE transaction."""
    priced = price_lines(db, lines)
    # Promise an ETA from the kitchen queue AS IT IS NOW (before this order joins it).
    load = get_kitchen_load(db, [(l["menu_item_id"], l["quantity"]) for l in priced["lines"]])
    eta = max(config.MIN_ETA_MINUTES, load["estimated_ready_minutes"])
    try:
        order = Order(
            customer_name=customer_name.strip(),
            status="pending",
            total_amount=priced["total_amount"],
            source=source,
            session_id=session_id,
            is_demo=is_demo,
            tracking_code=_new_tracking_code(db),
            eta_minutes=eta,
            order_type=order_type if order_type in ("takeaway", "dine_in") else "takeaway",
            table_number=(table_number or None),
            notes=((notes or "").strip()[:300] or None),
        )
        db.add(order)
        db.flush()
        db.add(OrderStatusEvent(order_id=order.id, status="pending"))
        for line in priced["lines"]:
            db.add(OrderItem(order_id=order.id, menu_item_id=line["menu_item_id"],
                             quantity=line["quantity"], unit_price=line["unit_price"]))
            item = db.get(MenuItem, line["menu_item_id"])
            if item.stock_quantity is not None:
                item.stock_quantity -= line["quantity"]
                if item.stock_quantity <= 0:
                    item.available = False  # sold out
        db.commit()
        db.refresh(order)
        return order
    except Exception:
        db.rollback()
        raise


def restore_stock(db: Session, order: Order) -> None:
    for oi in db.query(OrderItem).filter(OrderItem.order_id == order.id).all():
        item = db.get(MenuItem, oi.menu_item_id)
        if item is not None and item.stock_quantity is not None:
            was_zero = item.stock_quantity <= 0
            item.stock_quantity += oi.quantity
            if was_zero and item.stock_quantity > 0:
                item.available = True


def set_status(db: Session, order: Order, new_status: str) -> None:
    """Change status, record the timestamped event, restore stock on cancel. Caller commits."""
    if order.status == new_status:
        return
    order.status = new_status
    db.add(OrderStatusEvent(order_id=order.id, status=new_status))
    if new_status == "cancelled":
        restore_stock(db, order)


def orders_to_responses(db: Session, orders: list[Order]) -> list[OrderResponse]:
    """Build API responses for many orders with ONE items query (no N+1)."""
    if not orders:
        return []
    items_by_order: dict[int, list[OrderItem]] = defaultdict(list)
    rows = (
        db.query(OrderItem)
        .filter(OrderItem.order_id.in_([o.id for o in orders]))
        .order_by(OrderItem.id)
        .all()
    )
    for row in rows:
        items_by_order[row.order_id].append(row)
    return [
        OrderResponse(
            id=o.id, customer_name=o.customer_name, status=o.status,
            total_amount=o.total_amount, created_at=o.created_at,
            items=items_by_order.get(o.id, []),
            tracking_code=o.tracking_code, eta_minutes=o.eta_minutes,
            order_type=o.order_type or "takeaway", table_number=o.table_number, notes=o.notes,
        )
        for o in orders
    ]


def order_to_response(db: Session, order: Order) -> OrderResponse:
    return orders_to_responses(db, [order])[0]
