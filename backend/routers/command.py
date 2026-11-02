"""Owner Command Center API (owner login required)."""
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from auth import require_role
from database import get_db
from models import MenuItem
from services import command_service as cs
from services.copilot_service import answer

router = APIRouter(prefix="/api/owner", tags=["Command Center"], dependencies=[Depends(require_role("owner"))])


class Question(BaseModel):
    question: str = Field(min_length=2, max_length=300)


class CostUpdate(BaseModel):
    cost_price: int | None = Field(default=None, ge=0, le=100000)


@router.get("/pulse")
def pulse(db: Session = Depends(get_db)):
    return cs.pulse(db)


@router.get("/heatmap")
def heatmap(db: Session = Depends(get_db)):
    return cs.heatmap(db)


@router.get("/forecast")
def forecast(db: Session = Depends(get_db)):
    return cs.forecast(db)


@router.get("/alerts")
def alerts(db: Session = Depends(get_db)):
    return {"alerts": cs.alerts(db)}


@router.get("/menu-engineering")
def menu_engineering(db: Session = Depends(get_db)):
    return cs.menu_engineering(db)


@router.get("/combos")
def combos(db: Session = Depends(get_db)):
    return cs.combos(db)


@router.get("/simulate-rush")
def simulate_rush(orders: int = Query(20, ge=1, le=300), minutes: int = Query(10, ge=1, le=240),
                  stations: int | None = Query(None, ge=1, le=20), seed: int = 7, db: Session = Depends(get_db)):
    return cs.simulate_rush(db, orders, minutes, stations, seed)


@router.get("/floor")
def floor(db: Session = Depends(get_db)):
    return cs.floor(db)


@router.get("/activity")
def activity(limit: int = Query(25, ge=1, le=100), db: Session = Depends(get_db)):
    return {"events": cs.activity(db, limit)}


@router.get("/briefing")
def briefing(db: Session = Depends(get_db)):
    return cs.briefing(db)


@router.post("/copilot")
def copilot(body: Question, db: Session = Depends(get_db)):
    return answer(db, body.question)


@router.patch("/menu/{item_id}/cost")
def set_cost(item_id: int, body: CostUpdate, db: Session = Depends(get_db)):
    item = db.get(MenuItem, item_id)
    if item is None:
        raise HTTPException(404, "Menu item not found")
    item.cost_price = body.cost_price
    db.commit()
    return {"id": item.id, "name": item.name, "cost_price": item.cost_price}
