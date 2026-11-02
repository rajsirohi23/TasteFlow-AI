from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from auth import require_role
from database import get_db
from models import Order
from order_schemas import OrderCreate, OrderResponse, OrderStatusUpdate
from services.order_service import (
    OrderError,
    create_order,
    is_valid_status_transition,
    order_to_response,
    orders_to_responses,
    set_status,
)

router = APIRouter(prefix="/api/orders", tags=["Orders"])


def _get_order_or_404(db: Session, order_id: int) -> Order:
    order = db.get(Order, order_id)
    if order is None:
        raise HTTPException(status_code=404, detail=f"Order {order_id} was not found")
    return order


@router.post("", response_model=OrderResponse, status_code=201)
def create_order_endpoint(order_data: OrderCreate, db: Session = Depends(get_db)):
    try:
        order = create_order(
            db,
            order_data.customer_name,
            [(i.menu_item_id, i.quantity) for i in order_data.items],
            source="web",
            order_type=order_data.order_type,
            table_number=order_data.table_number,
            notes=order_data.notes,
        )
    except OrderError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return order_to_response(db, order)


@router.get("/{order_id}", response_model=OrderResponse)
def get_order(order_id: int, db: Session = Depends(get_db)):
    return order_to_response(db, _get_order_or_404(db, order_id))


@router.get("", response_model=list[OrderResponse], dependencies=[Depends(require_role("kitchen"))])
def list_orders(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    orders = (
        db.query(Order)
        .order_by(Order.created_at.desc(), Order.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return orders_to_responses(db, orders)


@router.patch("/{order_id}/status", response_model=OrderResponse, dependencies=[Depends(require_role("kitchen"))])
def update_order_status(
    order_id: int, status_data: OrderStatusUpdate, db: Session = Depends(get_db)
):
    order = _get_order_or_404(db, order_id)
    if not is_valid_status_transition(order.status, status_data.status):
        raise HTTPException(
            status_code=409,
            detail=f"Cannot change order status from '{order.status}' to '{status_data.status}'.",
        )
    set_status(db, order, status_data.status)
    db.commit()
    db.refresh(order)
    return order_to_response(db, order)


@router.patch("/{order_id}/cancel", response_model=OrderResponse)
def cancel_order(order_id: int, db: Session = Depends(get_db)):
    order = _get_order_or_404(db, order_id)
    if order.status != "pending":
        raise HTTPException(
            status_code=409,
            detail=f"Only pending orders can be cancelled. Current status: '{order.status}'.",
        )
    set_status(db, order, "cancelled")
    db.commit()
    db.refresh(order)
    return order_to_response(db, order)
