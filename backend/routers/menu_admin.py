"""Owner menu management: add, edit, archive and restore dishes.

Dishes are never hard-deleted because past orders reference them; "delete" archives a
dish (hidden from guests, the chat agents and ordering) and it can be restored."""
import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func
from sqlalchemy.orm import Session

from auth import require_role
from database import get_db
from models import MenuItem

router = APIRouter(prefix="/api/owner/menu", tags=["Menu Management"], dependencies=[Depends(require_role("owner"))])

SPICE_LEVELS = ("Mild", "Medium", "Hot", "Extra Hot")
PLACEHOLDER_IMAGE = "data/placeholder.svg"
_TAG_RE = re.compile(r"^[a-z0-9][a-z0-9 \-]{0,29}$")


def _clean_list(values: list[str], limit: int, max_len: int, what: str) -> list[str]:
    out: list[str] = []
    for v in values:
        v = " ".join(str(v).split())
        if not v:
            continue
        if len(v) > max_len:
            raise ValueError(f"Each {what} must be at most {max_len} characters")
        if v.lower() not in [o.lower() for o in out]:
            out.append(v)
    if len(out) > limit:
        raise ValueError(f"At most {limit} {what}s are allowed")
    return out


class DishBase(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=80)
    price: int | None = Field(default=None, ge=1, le=100000)
    category: str | None = Field(default=None, min_length=2, max_length=40)
    description: str | None = Field(default=None, max_length=300)
    ingredients: list[str] | None = None
    dietary_tags: list[str] | None = None
    spice_level: str | None = None
    image: str | None = Field(default=None, max_length=500)
    available: bool | None = None
    prep_minutes: int | None = Field(default=None, ge=1, le=120)
    stock_quantity: int | None = Field(default=None, ge=0, le=100000)
    cost_price: int | None = Field(default=None, ge=0, le=100000)

    @field_validator("name", "category", "description")
    @classmethod
    def strip_text(cls, v):
        return " ".join(v.split()) if isinstance(v, str) else v

    @field_validator("ingredients")
    @classmethod
    def check_ingredients(cls, v):
        return None if v is None else _clean_list(v, 25, 40, "ingredient")

    @field_validator("dietary_tags")
    @classmethod
    def check_tags(cls, v):
        if v is None:
            return None
        tags = [t.strip().lower() for t in _clean_list(v, 8, 30, "dietary tag")]
        bad = [t for t in tags if not _TAG_RE.match(t)]
        if bad:
            raise ValueError(f"Invalid dietary tag: {bad[0]}")
        return tags

    @field_validator("spice_level")
    @classmethod
    def check_spice(cls, v):
        if v is None:
            return None
        match = next((s for s in SPICE_LEVELS if s.lower() == v.strip().lower()), None)
        if match is None:
            raise ValueError(f"Spice level must be one of {', '.join(SPICE_LEVELS)}")
        return match

    @field_validator("image")
    @classmethod
    def check_image(cls, v):
        if v is None or not v.strip():
            return None
        v = v.strip()
        if not (v.startswith("https://") or v.startswith("http://") or re.match(r"^data/[\w\-./]+$", v)):
            raise ValueError("Image must be an http(s) URL or a path inside the data/ folder")
        return v


class DishCreate(DishBase):
    name: str = Field(min_length=2, max_length=80)
    price: int = Field(ge=1, le=100000)
    category: str = Field(min_length=2, max_length=40)


def to_dict(m: MenuItem) -> dict:
    return {"id": m.id, "name": m.name, "price": m.price, "category": m.category, "description": m.description,
            "ingredients": m.ingredients or [], "dietary_tags": m.dietary_tags or [], "spice_level": m.spice_level,
            "image": m.image, "available": m.available, "archived": bool(m.archived), "prep_minutes": m.prep_minutes,
            "stock_quantity": m.stock_quantity, "cost_price": m.cost_price}


def _name_taken(db: Session, name: str, exclude_id: int | None = None) -> bool:
    q = db.query(MenuItem.id).filter(func.lower(MenuItem.name) == name.lower())
    if exclude_id is not None:
        q = q.filter(MenuItem.id != exclude_id)
    return q.first() is not None


@router.get("")
def list_all(db: Session = Depends(get_db)):
    """Every dish including archived ones (the public /api/menu hides archived)."""
    return [to_dict(m) for m in db.query(MenuItem).order_by(MenuItem.id).all()]


@router.post("", status_code=201)
def create_dish(body: DishCreate, db: Session = Depends(get_db)):
    if _name_taken(db, body.name):
        raise HTTPException(409, f"A dish named '{body.name}' already exists")
    stock = body.stock_quantity
    item = MenuItem(
        name=body.name, price=body.price, category=body.category, description=body.description or "",
        ingredients=body.ingredients or [], dietary_tags=body.dietary_tags or [], spice_level=body.spice_level or "Mild",
        image=body.image or PLACEHOLDER_IMAGE, available=(body.available if body.available is not None else True) and (stock is None or stock > 0),
        prep_minutes=body.prep_minutes, stock_quantity=stock, cost_price=body.cost_price, archived=False)
    db.add(item)
    db.commit()
    db.refresh(item)
    return to_dict(item)


@router.patch("/{item_id}")
def update_dish(item_id: int, body: DishBase, db: Session = Depends(get_db)):
    item = db.get(MenuItem, item_id)
    if item is None:
        raise HTTPException(404, "Dish not found")
    changes = body.model_dump(exclude_unset=True)
    if "name" in changes and changes["name"] is None or "price" in changes and changes["price"] is None or "category" in changes and changes["category"] is None:
        raise HTTPException(422, "name, price and category cannot be empty")
    if "name" in changes and _name_taken(db, changes["name"], item_id):
        raise HTTPException(409, f"A dish named '{changes['name']}' already exists")
    if item.archived and changes.get("available"):
        raise HTTPException(409, "Restore the dish before making it available")
    if "image" in changes and not changes["image"]:
        changes["image"] = PLACEHOLDER_IMAGE
    for field, value in changes.items():
        if field in ("description", "spice_level") and value is None:
            continue
        if field in ("ingredients", "dietary_tags") and value is None:
            value = []
        setattr(item, field, value)
    if "stock_quantity" in changes and "available" not in changes and not item.archived:
        item.available = item.stock_quantity is None or item.stock_quantity > 0
    db.commit()
    db.refresh(item)
    return to_dict(item)


@router.delete("/{item_id}")
def archive_dish(item_id: int, db: Session = Depends(get_db)):
    item = db.get(MenuItem, item_id)
    if item is None:
        raise HTTPException(404, "Dish not found")
    item.archived, item.available = True, False
    db.commit()
    return {**to_dict(item), "message": f"{item.name} was removed from the menu. Past orders are unaffected; you can restore it."}


@router.post("/{item_id}/restore")
def restore_dish(item_id: int, db: Session = Depends(get_db)):
    item = db.get(MenuItem, item_id)
    if item is None:
        raise HTTPException(404, "Dish not found")
    item.archived = False
    item.available = item.stock_quantity is None or item.stock_quantity > 0
    db.commit()
    return to_dict(item)
