from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from database import get_db
from models import MenuItem
from schemas import MenuItemResponse

router = APIRouter(
    prefix="/api/menu",
    tags=["Menu"],
)


@router.get("", response_model=list[MenuItemResponse])
def get_menu(
    category: str | None = Query(default=None),
    diet: str | None = Query(default=None),
    max_price: int | None = Query(default=None, ge=0),
    available_only: bool = Query(default=False),
    db: Session = Depends(get_db),
):
    query = db.query(MenuItem).filter(MenuItem.archived.is_(False))

    # Filter by category, ignoring uppercase/lowercase differences.
    if category:
        query = query.filter(
            func.lower(MenuItem.category) == category.strip().lower()
        )

    # Apply database filters first.
    if max_price is not None:
        query = query.filter(MenuItem.price <= max_price)

    if available_only:
        query = query.filter(MenuItem.available.is_(True))

    # Keep menu ordering consistent.
    items = query.order_by(MenuItem.id).all()

    # SQLite JSON filtering can vary, so filter dietary tags in Python.
    if diet:
        requested_diet = diet.strip().lower()
        items = [
            item
            for item in items
            if any(
                tag.lower() == requested_diet
                for tag in (item.dietary_tags or [])
            )
        ]

    return items


@router.get("/{item_id}", response_model=MenuItemResponse)
def get_menu_item(
    item_id: int,
    db: Session = Depends(get_db),
):
    item = db.get(MenuItem, item_id)

    if item is None or item.archived:
        raise HTTPException(
            status_code=404,
            detail=f"Menu item with ID {item_id} was not found",
        )

    return item