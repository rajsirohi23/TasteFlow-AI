
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class OrderItemCreate(BaseModel):
    menu_item_id: int = Field(gt=0)
    quantity: int = Field(ge=1, le=50)


class OrderCreate(BaseModel):
    customer_name: str = Field(min_length=2, max_length=120)
    items: list[OrderItemCreate] = Field(min_length=1)
    order_type: Literal["takeaway", "dine_in"] = "takeaway"
    table_number: str | None = Field(default=None, max_length=10)
    notes: str | None = Field(default=None, max_length=300)


class OrderItemResponse(BaseModel):
    id: int
    menu_item_id: int
    quantity: int
    unit_price: int

    model_config = ConfigDict(from_attributes=True)


class OrderResponse(BaseModel):
    id: int
    customer_name: str
    status: str
    total_amount: int
    created_at: datetime
    items: list[OrderItemResponse]
    tracking_code: str | None = None
    eta_minutes: int | None = None
    order_type: str = "takeaway"
    table_number: str | None = None
    notes: str | None = None

    model_config = ConfigDict(from_attributes=True)


class OrderStatusUpdate(BaseModel):
    status: Literal[
        "pending",
        "preparing",
        "ready",
        "completed",
    ]



class MenuAvailabilityUpdate(BaseModel):
    available: bool
