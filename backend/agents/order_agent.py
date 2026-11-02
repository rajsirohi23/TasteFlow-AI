
from sqlalchemy.orm import Session

from models import MenuItem
from order_schemas import OrderCreate


def prepare_order_preview(
    db: Session,
    order_data: OrderCreate,
) -> dict:
    """
    Prepare an order summary for customer review.

    This function does not create an order or modify the database.
    The existing orders API remains responsible for final creation.
    """

    preview_items = []
    total_amount = 0

    for requested_item in order_data.items:
        menu_item = db.get(MenuItem, requested_item.menu_item_id)

        if menu_item is None:
            raise ValueError(
                f"Menu item {requested_item.menu_item_id} was not found."
            )

        if not menu_item.available:
            raise ValueError(
                f"{menu_item.name} is currently unavailable."
            )

        quantity = requested_item.quantity
        unit_price = menu_item.price
        subtotal = unit_price * quantity

        preview_items.append(
            {
                "menu_item_id": menu_item.id,
                "name": menu_item.name,
                "quantity": quantity,
                "unit_price": unit_price,
                "subtotal": subtotal,
            }
        )

        total_amount += subtotal

    return {
        "customer_name": order_data.customer_name.strip(),
        "items": preview_items,
        "total_items": sum(
            item["quantity"] for item in preview_items
        ),
        "total_amount": total_amount,
        "requires_confirmation": True,
    }

