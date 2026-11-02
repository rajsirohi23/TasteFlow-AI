from fastapi import APIRouter, Depends, HTTPException, Query
from auth import require_role
from pydantic import BaseModel, Field
from models import Feedback
from services.insights_service import build_insights, unmet_demand_summary
from services.ops_service import feedback_summary, inventory_summary, operations_summary
from sqlalchemy import func
from sqlalchemy.orm import Session

from database import get_db
from models import MenuItem, Order, OrderItem
from order_schemas import MenuAvailabilityUpdate
from datetime import date, datetime, time, timedelta

router = APIRouter(
    prefix="/api/owner",
    tags=["Owner Analytics"],
    dependencies=[Depends(require_role("owner"))],
)


@router.get("/insights")
def get_insights(db: Session = Depends(get_db)):
    """Data-backed insight sentences with their evidence (see insights_service)."""
    return build_insights(db)


class StockUpdate(BaseModel):
    stock_quantity: int | None = Field(default=None, ge=0, le=100000)  # null = stop tracking


@router.get("/operations")
def get_operations(db: Session = Depends(get_db)):
    """Measured kitchen speed (placed -> ready) from status timestamps."""
    return operations_summary(db)


@router.get("/feedback")
def get_feedback(db: Session = Depends(get_db)):
    return feedback_summary(db, recent=20)


@router.patch("/feedback/{feedback_id}/resolve")
def resolve_feedback(feedback_id: int, db: Session = Depends(get_db)):
    row = db.get(Feedback, feedback_id)
    if row is None:
        raise HTTPException(404, "Feedback not found")
    row.resolved = True
    db.commit()
    return {"id": row.id, "resolved": True}


@router.get("/inventory")
def get_inventory(db: Session = Depends(get_db)):
    return inventory_summary(db)


@router.patch("/menu/{item_id}/stock")
def set_stock(item_id: int, body: StockUpdate, db: Session = Depends(get_db)):
    """Set or clear a dish's stock. A tracked dish with 0 stock is automatically unavailable."""
    item = db.get(MenuItem, item_id)
    if item is None:
        raise HTTPException(404, "Menu item not found")
    item.stock_quantity = body.stock_quantity
    item.available = body.stock_quantity is None or body.stock_quantity > 0
    db.commit()
    return {"id": item.id, "name": item.name, "stock_quantity": item.stock_quantity, "available": item.available}


@router.get("/unmet-demand")
def get_unmet_demand(limit: int = Query(default=10, ge=1, le=50), db: Session = Depends(get_db)):
    """What guests asked for but the menu could not satisfy."""
    return {"requests": unmet_demand_summary(db, limit)}



@router.get("/summary")
def get_owner_summary(
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    db: Session = Depends(get_db),
):
    # Validate the date range.
    if start_date and end_date and start_date > end_date:
        raise HTTPException(
            status_code=422,
            detail="start_date must be on or before end_date",
        )

    # Build a shared query for the requested date range.
    orders_query = db.query(Order)

    if start_date:
        start_datetime = datetime.combine(start_date, time.min)
        orders_query = orders_query.filter(
            Order.created_at >= start_datetime
        )

    if end_date:
        end_datetime = datetime.combine(
            end_date + timedelta(days=1),
            time.min,
        )
        orders_query = orders_query.filter(
            Order.created_at < end_datetime
        )

    # Total orders within the selected date range.
    total_orders = orders_query.count()

    # Completed orders within the selected date range.
    completed_orders = orders_query.filter(
        Order.status == "completed"
    ).count()

    # Cancelled orders within the selected date range.
    cancelled_orders = orders_query.filter(
        Order.status == "cancelled"
    ).count()

    # Active orders within the selected date range.
    active_orders = orders_query.filter(
        Order.status.in_(["pending", "preparing", "ready"])
    ).count()

    # Recorded order value, excluding cancelled orders.
    non_cancelled_value = (
        db.query(func.sum(Order.total_amount))
        .filter(Order.id.in_(orders_query.with_entities(Order.id)))
        .filter(Order.status != "cancelled")
        .scalar()
        or 0
    )

    # Completed order value within the selected date range.
    completed_value = (
        db.query(func.sum(Order.total_amount))
        .filter(Order.id.in_(orders_query.with_entities(Order.id)))
        .filter(Order.status == "completed")
        .scalar()
        or 0
    )

    # Average completed order value.
    average_completed_value = (
        round(completed_value / completed_orders, 2)
        if completed_orders > 0
        else 0
    )

    return {
        "total_orders": total_orders,
        "active_orders": active_orders,
        "completed_orders": completed_orders,
        "cancelled_orders": cancelled_orders,
        "non_cancelled_order_value": non_cancelled_value,
        "completed_order_value": completed_value,
        "average_completed_order_value": average_completed_value,
        "currency": "INR",
        "revenue_note": (
            "These are recorded order values, not verified payment revenue."
        ),
    }





@router.get("/popular-dishes")
def get_popular_dishes(
    limit: int = Query(default=10, ge=1, le=50),
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    db: Session = Depends(get_db),
):
    # Validate the date range.
    if start_date and end_date and start_date > end_date:
        raise HTTPException(
            status_code=422,
            detail="start_date must be on or before end_date",
        )

    # Build the existing popular-dish aggregation query.
    query = (
        db.query(
            MenuItem.id.label("menu_item_id"),
            MenuItem.name.label("name"),
            func.sum(OrderItem.quantity).label("quantity_ordered"),
            func.count(
                func.distinct(OrderItem.order_id)
            ).label("order_count"),
            func.sum(
                OrderItem.unit_price * OrderItem.quantity
            ).label("recorded_value"),
        )
        .join(
            OrderItem,
            OrderItem.menu_item_id == MenuItem.id,
        )
        .join(
            Order,
            Order.id == OrderItem.order_id,
        )
        .filter(Order.status != "cancelled")
    )

    # Apply the inclusive start-date filter.
    if start_date:
        start_datetime = datetime.combine(start_date, time.min)
        query = query.filter(
            Order.created_at >= start_datetime
        )

    # Include the entire end date by using the next day's midnight.
    if end_date:
        end_datetime = datetime.combine(
            end_date + timedelta(days=1),
            time.min,
        )
        query = query.filter(
            Order.created_at < end_datetime
        )

    # Preserve the existing grouping, ordering, and limit.
    results = (
        query
        .group_by(MenuItem.id, MenuItem.name)
        .order_by(
            func.sum(OrderItem.quantity).desc(),
            MenuItem.id.asc(),
        )
        .limit(limit)
        .all()
    )

    return [
        {
            "menu_item_id": row.menu_item_id,
            "name": row.name,
            "quantity_ordered": row.quantity_ordered,
            "order_count": row.order_count,
            "recorded_value": row.recorded_value,
            "currency": "INR",
        }
        for row in results
    ]






@router.get("/low-demand-dishes")
def get_low_demand_dishes(
    threshold: int = Query(default=2, ge=0, le=1000),
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    db: Session = Depends(get_db),
):
    # Validate the date range.
    if start_date and end_date and start_date > end_date:
        raise HTTPException(
            status_code=422,
            detail="start_date must be on or before end_date",
        )

    # Start with non-cancelled orders.
    demand_query = (
        db.query(
            OrderItem.menu_item_id,
            func.sum(OrderItem.quantity).label("quantity_ordered"),
            func.count(
                func.distinct(OrderItem.order_id)
            ).label("order_count"),
        )
        .join(Order, Order.id == OrderItem.order_id)
        .filter(Order.status != "cancelled")
    )

    # Apply the inclusive start-date filter.
    if start_date:
        start_datetime = datetime.combine(start_date, time.min)
        demand_query = demand_query.filter(
            Order.created_at >= start_datetime
        )

    # Include the entire end date.
    if end_date:
        end_datetime = datetime.combine(
            end_date + timedelta(days=1),
            time.min,
        )
        demand_query = demand_query.filter(
            Order.created_at < end_datetime
        )

    demand_rows = (
        demand_query
        .group_by(OrderItem.menu_item_id)
        .all()
    )

    demand_by_item = {
        row.menu_item_id: {
            "quantity_ordered": row.quantity_ordered,
            "order_count": row.order_count,
        }
        for row in demand_rows
    }

    # Include every menu item, even if it had no orders
    # during the selected date range.
    menu_items = db.query(MenuItem).order_by(MenuItem.id).all()

    results = []

    for item in menu_items:
        demand = demand_by_item.get(
            item.id,
            {"quantity_ordered": 0, "order_count": 0},
        )

        quantity_ordered = demand["quantity_ordered"]

        if quantity_ordered > threshold:
            continue

        results.append(
            {
                "menu_item_id": item.id,
                "name": item.name,
                "available": item.available,
                "quantity_ordered": quantity_ordered,
                "order_count": demand["order_count"],
                "demand_label": (
                    "never_ordered"
                    if quantity_ordered == 0
                    else "low_demand"
                ),
            }
        )

    # Show dishes with the least demand first.
    results.sort(
        key=lambda item: (
            item["quantity_ordered"],
            item["menu_item_id"],
        )
    )

    return {
        "threshold": threshold,
        "count": len(results),
        "dishes": results,
    }






@router.patch("/menu/{item_id}/availability")
def update_menu_availability(
    item_id: int,
    availability_data: MenuAvailabilityUpdate,
    db: Session = Depends(get_db),
):
    item = db.get(MenuItem, item_id)

    if item is None:
        raise HTTPException(
            status_code=404,
            detail=f"Menu item {item_id} was not found",
        )

    try:
        item.available = availability_data.available
        db.commit()
        db.refresh(item)

        return {
            "id": item.id,
            "name": item.name,
            "available": item.available,
            "message": (
                "Menu item is now available"
                if item.available
                else "Menu item is now unavailable"
            ),
        }

    except Exception:
        db.rollback()
        raise




@router.get("/menu/{item_id}/history")
def get_dish_order_history(
    item_id: int,
    limit: int = Query(default=10, ge=1, le=50),
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    db: Session = Depends(get_db),
):
    # Validate the date range before running either query.
    if start_date and end_date and start_date > end_date:
        raise HTTPException(
            status_code=422,
            detail="start_date must be on or before end_date",
        )

    # Check that the dish exists.
    menu_item = db.get(MenuItem, item_id)

    if menu_item is None:
        raise HTTPException(
            status_code=404,
            detail=f"Menu item {item_id} was not found",
        )

    # Aggregate demand, excluding cancelled orders.
    stats_query = (
        db.query(
            func.coalesce(
                func.sum(OrderItem.quantity), 0
            ).label("quantity_ordered"),
            func.count(
                func.distinct(OrderItem.order_id)
            ).label("order_count"),
            func.coalesce(
                func.sum(
                    OrderItem.unit_price * OrderItem.quantity
                ),
                0,
            ).label("recorded_value"),
        )
        .join(Order, Order.id == OrderItem.order_id)
        .filter(
            OrderItem.menu_item_id == item_id,
            Order.status != "cancelled",
        )
    )

    if start_date:
        start_datetime = datetime.combine(start_date, time.min)
        stats_query = stats_query.filter(
            Order.created_at >= start_datetime
        )

    if end_date:
        end_datetime = datetime.combine(
            end_date + timedelta(days=1),
            time.min,
        )
        stats_query = stats_query.filter(
            Order.created_at < end_datetime
        )

    stats = stats_query.one()

    # Fetch recent eligible orders, excluding cancelled orders.
    recent_query = (
        db.query(Order, OrderItem)
        .join(OrderItem, OrderItem.order_id == Order.id)
        .filter(
            OrderItem.menu_item_id == item_id,
            Order.status != "cancelled",
        )
    )

    if start_date:
        start_datetime = datetime.combine(start_date, time.min)
        recent_query = recent_query.filter(
            Order.created_at >= start_datetime
        )

    if end_date:
        end_datetime = datetime.combine(
            end_date + timedelta(days=1),
            time.min,
        )
        recent_query = recent_query.filter(
            Order.created_at < end_datetime
        )

    recent_rows = (
        recent_query
        .order_by(Order.created_at.desc(), Order.id.desc())
        .limit(limit)
        .all()
    )

    recent_orders = [
        {
            "order_id": order.id,
            "created_at": order.created_at,
            "status": order.status,
            "quantity": order_item.quantity,
            "unit_price": order_item.unit_price,
            "recorded_value": (
                order_item.quantity * order_item.unit_price
            ),
        }
        for order, order_item in recent_rows
    ]

    return {
        "menu_item_id": menu_item.id,
        "name": menu_item.name,
        "available": menu_item.available,
        "quantity_ordered": stats.quantity_ordered,
        "order_count": stats.order_count,
        "recorded_value": stats.recorded_value,
        "currency": "INR",
        "recent_orders": recent_orders,
    }



@router.get("/busy-periods")
def get_busy_periods(
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    db: Session = Depends(get_db),
):
    # Validate the date range.
    if start_date and end_date and start_date > end_date:
        raise HTTPException(
            status_code=422,
            detail="start_date must be on or before end_date",
        )

    # Start with non-cancelled orders.
    query = db.query(Order).filter(Order.status != "cancelled")

    # Apply the inclusive start date.
    if start_date:
        start_datetime = datetime.combine(start_date, time.min)
        query = query.filter(Order.created_at >= start_datetime)

    # Include the entire end date.
    if end_date:
        end_datetime = datetime.combine(
            end_date + timedelta(days=1),
            time.min,
        )
        query = query.filter(Order.created_at < end_datetime)

    # Fetch matching timestamps and group them by hour in Python.
    orders = query.with_entities(Order.created_at).all()

    hourly_counts = {}

    for (created_at,) in orders:
        hour = created_at.hour
        hourly_counts[hour] = hourly_counts.get(hour, 0) + 1

    # Sort by order count, then by hour for consistent results.
    busy_periods = [
        {
            "hour": hour,
            "order_count": order_count,
        }
        for hour, order_count in sorted(
            hourly_counts.items(),
            key=lambda item: (-item[1], item[0]),
        )
    ]

    return {
        "period": "hour",
        "count": len(busy_periods),
        "busy_periods": busy_periods,
    }





@router.get("/daily-sales")
def get_daily_sales(
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    db: Session = Depends(get_db),
):
    if start_date and end_date and start_date > end_date:
        raise HTTPException(
            status_code=422,
            detail="start_date must be on or before end_date",
        )

    query = db.query(Order).filter(Order.status != "cancelled")

    if start_date:
        start_datetime = datetime.combine(start_date, time.min)
        query = query.filter(Order.created_at >= start_datetime)

    if end_date:
        end_datetime = datetime.combine(
            end_date + timedelta(days=1),
            time.min,
        )
        query = query.filter(Order.created_at < end_datetime)

    orders = query.order_by(Order.created_at.asc()).all()

    daily_data = {}

    for order in orders:
        order_date = order.created_at.date().isoformat()

        if order_date not in daily_data:
            daily_data[order_date] = {
                "date": order_date,
                "order_count": 0,
                "revenue": 0.0,
            }

        daily_data[order_date]["order_count"] += 1

        # Fetch items through the existing order_id foreign key.
        items = (
            db.query(OrderItem)
            .filter(OrderItem.order_id == order.id)
            .all()
        )

        for item in items:
            daily_data[order_date]["revenue"] += (
                float(item.unit_price) * item.quantity
            )

    daily_sales = [
        {
            **data,
            "revenue": round(data["revenue"], 2),
        }
        for data in daily_data.values()
    ]

    return {
        "start_date": start_date.isoformat() if start_date else None,
        "end_date": end_date.isoformat() if end_date else None,
        "count": len(daily_sales),
        "daily_sales": daily_sales,
    }





@router.get("/order-status")
def get_order_status_analytics(
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    db: Session = Depends(get_db),
):
    # Validate the date range.
    if start_date and end_date and start_date > end_date:
        raise HTTPException(
            status_code=422,
            detail="start_date must be on or before end_date",
        )

    # Exclude cancelled orders.
    query = db.query(Order).filter(
        Order.status != "cancelled"
    )

    # Apply the start-date filter.
    if start_date:
        start_datetime = datetime.combine(start_date, time.min)
        query = query.filter(
            Order.created_at >= start_datetime
        )

    # Apply the end-date filter, including the entire end date.
    if end_date:
        end_datetime = datetime.combine(
            end_date + timedelta(days=1),
            time.min,
        )
        query = query.filter(
            Order.created_at < end_datetime
        )

    # Count orders grouped by status.
    results = (
        query.with_entities(
            Order.status,
            func.count(Order.id),
        )
        .group_by(Order.status)
        .all()
    )

    status_counts = {
        status: count
        for status, count in results
    }

    # Calculate total orders.
    total_orders = sum(status_counts.values())

    # Calculate each status percentage safely.
    status_percentages = (
        {
            status: round(
                (count / total_orders) * 100,
                2,
            )
            for status, count in status_counts.items()
        }
        if total_orders > 0
        else {}
    )

    return {
        "start_date": start_date.isoformat() if start_date else None,
        "end_date": end_date.isoformat() if end_date else None,
        "total_orders": total_orders,
        "status_counts": status_counts,
        "status_percentages": status_percentages,
    }





@router.get("/average-order-value")
def get_average_order_value(
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    db: Session = Depends(get_db),
):
    if start_date and end_date and start_date > end_date:
        raise HTTPException(
            status_code=422,
            detail="start_date must be on or before end_date",
        )

    query = db.query(Order).filter(Order.status != "cancelled")

    if start_date:
        start_datetime = datetime.combine(start_date, time.min)
        query = query.filter(Order.created_at >= start_datetime)

    if end_date:
        end_datetime = datetime.combine(
            end_date + timedelta(days=1),
            time.min,
        )
        query = query.filter(Order.created_at < end_datetime)

    orders = query.all()

    total_revenue = 0.0

    for order in orders:
        items = (
            db.query(OrderItem)
            .filter(OrderItem.order_id == order.id)
            .all()
        )

        for item in items:
            total_revenue += float(item.unit_price) * item.quantity

    total_revenue = round(total_revenue, 2)
    total_orders = len(orders)

    average_order_value = (
        round(total_revenue / total_orders, 2)
        if total_orders > 0
        else 0.0
    )

    return {
        "start_date": start_date.isoformat() if start_date else None,
        "end_date": end_date.isoformat() if end_date else None,
        "total_orders": total_orders,
        "total_revenue": total_revenue,
        "average_order_value": average_order_value,
    }




@router.get("/revenue-by-status")
def get_revenue_by_status(
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    db: Session = Depends(get_db),
):
    if start_date and end_date and start_date > end_date:
        raise HTTPException(
            status_code=422,
            detail="start_date must be on or before end_date",
        )

    query = db.query(Order).filter(Order.status != "cancelled")

    if start_date:
        start_datetime = datetime.combine(start_date, time.min)
        query = query.filter(Order.created_at >= start_datetime)

    if end_date:
        end_datetime = datetime.combine(
            end_date + timedelta(days=1),
            time.min,
        )
        query = query.filter(Order.created_at < end_datetime)

    # Join order items and aggregate revenue in the database.
    results = (
        query.with_entities(
            Order.status,
            func.count(func.distinct(Order.id)).label("order_count"),
            func.coalesce(
                func.sum(OrderItem.unit_price * OrderItem.quantity),
                0,
            ).label("revenue"),
        )
        .outerjoin(OrderItem, OrderItem.order_id == Order.id)
        .group_by(Order.status)
        .order_by(Order.status)
        .all()
    )

    status_breakdown = {
        status: {
            "order_count": order_count,
            "revenue": round(float(revenue), 2),
        }
        for status, order_count, revenue in results
    }

    total_revenue = round(
        sum(item["revenue"] for item in status_breakdown.values()),
        2,
    )

    return {
        "start_date": start_date.isoformat() if start_date else None,
        "end_date": end_date.isoformat() if end_date else None,
        "total_revenue": total_revenue,
        "status_breakdown": status_breakdown,
    }




@router.get("/top-revenue-dishes")
def get_top_revenue_dishes(
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    limit: int = Query(default=10, ge=1, le=100),
    db: Session = Depends(get_db),
):
    if start_date and end_date and start_date > end_date:
        raise HTTPException(
            status_code=422,
            detail="start_date must be on or before end_date",
        )

    query = (
        db.query(
            MenuItem.id.label("menu_item_id"),
            MenuItem.name.label("dish_name"),
            func.sum(OrderItem.quantity).label("quantity_sold"),
            func.sum(
                OrderItem.unit_price * OrderItem.quantity
            ).label("revenue"),
        )
        .join(OrderItem, OrderItem.menu_item_id == MenuItem.id)
        .join(Order, Order.id == OrderItem.order_id)
        .filter(Order.status != "cancelled")
    )

    if start_date:
        start_datetime = datetime.combine(start_date, time.min)
        query = query.filter(Order.created_at >= start_datetime)

    if end_date:
        end_datetime = datetime.combine(
            end_date + timedelta(days=1),
            time.min,
        )
        query = query.filter(Order.created_at < end_datetime)

    results = (
        query.group_by(MenuItem.id, MenuItem.name)
        .order_by(
            func.sum(
                OrderItem.unit_price * OrderItem.quantity
            ).desc(),
            MenuItem.name.asc(),
        )
        .limit(limit)
        .all()
    )

    dishes = [
        {
            "menu_item_id": menu_item_id,
            "dish_name": dish_name,
            "quantity_sold": quantity_sold,
            "revenue": round(float(revenue), 2),
        }
        for menu_item_id, dish_name, quantity_sold, revenue in results
    ]

    return {
        "start_date": start_date.isoformat() if start_date else None,
        "end_date": end_date.isoformat() if end_date else None,
        "count": len(dishes),
        "dishes": dishes,
    }
