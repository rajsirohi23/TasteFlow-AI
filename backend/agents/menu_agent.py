"""Smart Menu & Nutrition Agent: filter, rank and EXPLAIN real menu items.

Everything here reads the real database. Nothing is invented:
- "high protein" uses protein_g when a dish has it, otherwise it only flags
  dishes whose ingredient list contains a protein-rich ingredient, and says so.
"""
from sqlalchemy import func
from sqlalchemy.orm import Session

from models import MenuItem, Order, OrderItem

SPICE_ORDER = {"mild": 0, "medium": 1, "hot": 2, "extra hot": 3}

# Ingredient keywords that indicate a protein-rich dish (used only when we do
# not have numeric protein data for the dish).
PROTEIN_INGREDIENTS = (
    "paneer", "tofu", "lentil", "dal", "chickpea", "chana", "rajma", "beans",
    "egg", "chicken", "fish", "prawn", "mutton", "lamb", "soy", "quinoa",
    "peanut", "cheese", "yogurt", "curd", "greek",
)


def spice_rank(level: str | None) -> int:
    return SPICE_ORDER.get((level or "").strip().lower(), 0)


def protein_signal(item: MenuItem) -> tuple[bool, str | None]:
    """(is_protein_rich, explanation). Honest about where the claim comes from."""
    if item.protein_g is not None:
        return (item.protein_g >= 15), f"{item.protein_g} g protein ({item.nutrition_source or 'recorded'})"
    matches = [i for i in (item.ingredients or [])
               if any(k in i.lower() for k in PROTEIN_INGREDIENTS)]
    if matches:
        return True, "contains " + ", ".join(sorted(set(m.lower() for m in matches))[:3]) + " (ingredient-based, not measured)"
    return False, None


def get_dish_popularity(db: Session) -> dict[int, int]:
    """Return ordered quantities, excluding cancelled orders."""
    rows = (
        db.query(OrderItem.menu_item_id, func.sum(OrderItem.quantity).label("q"))
        .join(Order, Order.id == OrderItem.order_id)
        .filter(Order.status != "cancelled")
        .group_by(OrderItem.menu_item_id)
        .all()
    )
    return {item_id: int(q or 0) for item_id, q in rows}


def get_recommendation_reasons(
    item: MenuItem,
    budget: int | None,
    diet: str | None,
    category: str | None,
    spice_level: str | None,
    popularity: dict[int, int],
    max_spice_level: str | None = None,
    protein_focus: bool = False,
    prefer_fast: bool = False,
    prep_minutes: int | None = None,
) -> list[str]:
    """Explain which preferences and signals match a dish."""
    reasons = []
    if budget is not None and item.price <= budget:
        reasons.append("Fits your budget")
    if diet and any(t.strip().lower() == diet.strip().lower() for t in (item.dietary_tags or [])):
        reasons.append(f"Matches your {diet.strip()} preference")
    if category and item.category.strip().lower() == category.strip().lower():
        reasons.append(f"Matches your {category.strip()} category")
    if spice_level and item.spice_level.strip().lower() == spice_level.strip().lower():
        reasons.append(f"Matches your {spice_level.strip()} spice preference")
    if max_spice_level:
        reasons.append(f"{item.spice_level} spice, within your limit")
    if protein_focus:
        ok, why = protein_signal(item)
        if ok and why:
            reasons.append(f"Protein: {why}")
    if prefer_fast and prep_minutes:
        reasons.append(f"Quick to prepare right now (~{prep_minutes} min)")
    if popularity.get(item.id, 0) > 0:
        reasons.append("Popular based on previous orders")
    if not reasons:
        reasons.append("Matches your available menu options")
    return reasons


def recommend_menu_items(
    db: Session,
    budget: int | None = None,
    diet: str | None = None,
    category: str | None = None,
    spice_level: str | None = None,
    limit: int = 5,
    max_spice_level: str | None = None,
    exclude_ingredients: list[str] | None = None,
    protein_focus: bool = False,
    prefer_fast: bool = False,
    exclude_ids: set[int] | None = None,
) -> list[MenuItem]:
    """Filter, then rank, available menu items.

    Ranking uses only real signals: past popularity, protein evidence (when asked)
    and kitchen speed (when the kitchen is busy). It does NOT favour expensive
    dishes. Ties break by id so results are stable.
    """
    from services.kitchen_service import prep_minutes_for

    query = db.query(MenuItem).filter(MenuItem.available.is_(True))
    query = query.filter((MenuItem.stock_quantity.is_(None)) | (MenuItem.stock_quantity > 0))
    if budget is not None:
        query = query.filter(MenuItem.price <= budget)
    items = query.order_by(MenuItem.id).all()

    if diet:
        wanted = diet.strip().lower()
        items = [i for i in items if any(t.strip().lower() == wanted for t in (i.dietary_tags or []))]
    if category:
        wanted = category.strip().lower()
        items = [i for i in items if i.category.strip().lower() == wanted]
    if spice_level:
        wanted = spice_level.strip().lower()
        items = [i for i in items if i.spice_level.strip().lower() == wanted]
    if max_spice_level:
        ceiling = spice_rank(max_spice_level)
        items = [i for i in items if spice_rank(i.spice_level) <= ceiling]
    if exclude_ingredients:
        banned = [b.strip().lower() for b in exclude_ingredients if b.strip()]
        items = [i for i in items
                 if not any(b in ing.lower() for b in banned for ing in (i.ingredients or []))]
    if exclude_ids:
        items = [i for i in items if i.id not in exclude_ids]
    if protein_focus:
        # A "high-protein meal" is a meal: drinks and desserts only if asked for explicitly.
        if not category:
            items = [i for i in items if i.category not in ("Drinks", "Desserts")]
        items = [i for i in items if protein_signal(i)[0]]  # only dishes with evidence of protein

    popularity = get_dish_popularity(db)

    def score(item: MenuItem) -> int:
        s = min(popularity.get(item.id, 0), 10) * 2
        if protein_focus and item.protein_g is not None:
            s += min(item.protein_g // 5, 8)
        if prefer_fast:
            s += max(0, 12 - prep_minutes_for(item))
        if item.description and len(item.description.strip()) >= 30:
            s += 1
        return s

    return sorted(items, key=lambda i: (-score(i), i.id))[:limit]
