"""Public order tracking. Guests look up an order by its random tracking code
(not by the guessable numeric id) and only see their first name and items."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from database import get_db
from services.feedback_service import recovery_message, submit_feedback
from services.order_service import OrderError, set_status
from services.tracking_service import find_by_code, get_tracking

router = APIRouter(prefix="/api/track", tags=["Order Tracking"])


class FeedbackIn(BaseModel):
    rating: int = Field(ge=1, le=5)
    comment: str | None = Field(default=None, max_length=500)


def _order(db: Session, code: str):
    order = find_by_code(db, code)
    if order is None:
        raise HTTPException(404, "We couldn't find an order with that tracking code.")
    return order


@router.get("/{code}")
def track_order(code: str, db: Session = Depends(get_db)):
    return get_tracking(db, _order(db, code))


@router.patch("/{code}/cancel")
def cancel_tracked_order(code: str, db: Session = Depends(get_db)):
    order = _order(db, code)
    if order.status != "pending":
        raise HTTPException(409, f"Only orders that haven't started can be cancelled. Current status: '{order.status}'.")
    set_status(db, order, "cancelled")
    db.commit()
    return get_tracking(db, order)


@router.post("/{code}/feedback", status_code=201)
def rate_order(code: str, body: FeedbackIn, db: Session = Depends(get_db)):
    order = _order(db, code)
    try:
        row = submit_feedback(db, order, body.rating, body.comment)
    except OrderError as exc:
        raise HTTPException(exc.status_code, exc.message) from exc
    return {"id": row.id, "sentiment": row.sentiment, "message": recovery_message(row.rating)}
