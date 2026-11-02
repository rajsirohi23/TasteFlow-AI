"""Multi-agent orchestrator.

One customer message goes through:
  Supervisor (understand + route)  ->  specialist agent(s)  ->  composed reply

Specialists (each action is a recorded, inspectable step):
  menu          Smart Menu & Nutrition Agent
  order         Intelligent Order Agent
  kitchen       Kitchen Coordination Agent
  intelligence  Restaurant Intelligence Agent (staff only)

Safety rule: agents only DECIDE what to do. Prices, totals, availability, order
confirmation and saving are done by backend functions (services/*), never by
text generation. An order is only reported as placed after create_order()
returned an order id.
"""
import logging
import re

from sqlalchemy.orm import Session

import agents.nlu as nlu
from agents.menu_agent import get_dish_popularity, get_recommendation_reasons, recommend_menu_items
from agents.state import load_session, normalize_session_id, save_session
from agents.tracer import Tracer
from models import MenuItem, Order, UnmetDemand
from services.kitchen_service import get_kitchen_load, prep_minutes_for
from services.feedback_service import recovery_message, submit_feedback
from services.order_service import OrderError, create_order, price_lines, set_status
from services.tracking_service import get_tracking

log = logging.getLogger("tasteflow.agents")

AGENT_LABELS = {
    "supervisor": "Supervisor Agent",
    "menu": "Smart Menu & Nutrition Agent",
    "order": "Intelligent Order Agent",
    "kitchen": "Kitchen Coordination Agent",
    "intelligence": "Restaurant Intelligence Agent",
    "tracking": "Order Tracking Agent",
    "feedback": "Feedback & Service Recovery Agent",
    "inventory": "Inventory Agent",
}
ROUTES = {
    "recommend": "menu", "show_item": "menu",
    "add_item": "order", "remove_item": "order", "set_quantity": "order",
    "show_cart": "order", "clear_cart": "order", "checkout": "order",
    "provide_name": "order", "confirm_yes": "order", "decline": "order",
    "modify_order": "order", "cancel_order": "order", "order_status": "tracking",
    "set_order_type": "order", "add_note": "order", "reorder": "order",
    "give_feedback": "feedback", "feedback_summary": "feedback", "inventory": "inventory",
    "kitchen_status": "kitchen", "analytics": "intelligence",
}
CAPABILITIES = ("I can recommend dishes (try: “vegetarian under ₹300, not too spicy”), manage your cart, "
                "set dine-in or takeaway, place your order after you confirm it, track how many minutes are left, "
                "reorder, and take your feedback.")


def inr(n) -> str:
    return f"₹{int(n):,}" if float(n).is_integer() else f"₹{n:,.2f}"


# ---------------------------------------------------------------- helpers
def _menu_snapshot(db: Session) -> list[dict]:
    return [{"id": m.id, "name": m.name, "price": m.price, "category": m.category,
             "available": m.available, "spice_level": m.spice_level, "image": m.image,
             "dietary_tags": m.dietary_tags or [], "ingredients": m.ingredients or []}
            for m in db.query(MenuItem).filter(MenuItem.archived.is_(False)).order_by(MenuItem.id).all()]


def _vocab(menu: list[dict]) -> set[str]:
    words: set[str] = set()
    for m in menu:
        for ing in m["ingredients"]:
            ing = ing.lower().strip()
            words.add(ing)
            words.update(w for w in re.findall(r"[a-z]+", ing) if len(w) > 2)
    return words


def describe_prefs(p: dict) -> str:
    parts = []
    if p.get("diet"): parts.append(p["diet"])
    if p.get("category"): parts.append(p["category"].lower())
    if p.get("budget") is not None: parts.append(f"under {inr(p['budget'])}")
    if p.get("max_spice_level"): parts.append(f"spice up to {p['max_spice_level']}")
    if p.get("spice_level"): parts.append(f"{p['spice_level']} spice")
    if p.get("protein_focus"): parts.append("protein-rich")
    if p.get("exclude_ingredients"): parts.append("no " + ", no ".join(p["exclude_ingredients"]))
    return " · ".join(parts) or "no filters"


def cart_view(db: Session, state: dict) -> dict:
    """Priced cart from the DB. Dishes that vanished or sold out are dropped and reported."""
    keep, removed = [], []
    for line in state["cart"]:
        item = db.get(MenuItem, line["menu_item_id"])
        if item is None or not item.available:
            removed.append(item.name if item else f"item {line['menu_item_id']}")
        else:
            keep.append(line)
    state["cart"] = keep
    if not keep:
        return {"lines": [], "total_items": 0, "total_amount": 0, "removed": removed}
    priced = price_lines(db, [(l["menu_item_id"], l["quantity"]) for l in keep])
    return {**priced, "removed": removed}


def cart_text(view: dict) -> str:
    if not view["lines"]:
        return "Your cart is empty."
    rows = "; ".join(f"{l['quantity']} × {l['name']} ({inr(l['subtotal'])})" for l in view["lines"])
    return f"{rows}. Total {inr(view['total_amount'])}."


def _card(item: MenuItem, reasons: list[str]) -> dict:
    return {"id": item.id, "name": item.name, "price": item.price, "category": item.category,
            "spice_level": item.spice_level, "dietary_tags": item.dietary_tags or [],
            "image": item.image, "reasons": reasons}


def _add_to_cart(state: dict, item_id: int, qty: int) -> None:
    for line in state["cart"]:
        if line["menu_item_id"] == item_id:
            line["quantity"] = min(line["quantity"] + qty, 50)
            return
    state["cart"].append({"menu_item_id": item_id, "quantity": min(qty, 50)})


# ---------------------------------------------------------------- Menu agent
def _menu_search(ctx, prefs: dict, exclude_ids: set[int], prefer_fast: bool, explicit: set[str] = frozenset()):
    db, tr = ctx["db"], ctx["tracer"]
    args = dict(budget=prefs.get("budget"), diet=prefs.get("diet"), category=prefs.get("category"),
                spice_level=prefs.get("spice_level"), max_spice_level=prefs.get("max_spice_level"),
                exclude_ingredients=prefs.get("exclude_ingredients") or None,
                protein_focus=bool(prefs.get("protein_focus")), prefer_fast=prefer_fast,
                exclude_ids=exclude_ids or None, limit=4)
    with tr.step("menu", "search_menu", {k: v for k, v in args.items() if v}) as s:
        items = recommend_menu_items(db, **args)
        s["output"] = {"matches": [i.name for i in items]}
    relaxed: list[str] = []
    if not items:
        # Try progressively looser searches (never the diet: that is not negotiable).
        for label, drop in (("protein focus", "protein_focus"), ("spice limit", "max_spice_level"),
                            ("spice level", "spice_level"), ("budget", "budget")):
            if not args.get(drop) or drop in explicit:
                continue  # never relax something the guest just asked for
            args[drop] = False if drop == "protein_focus" else None
            relaxed.append(label)
            with tr.step("menu", "relax_search", {"dropped": relaxed}) as s:
                items = recommend_menu_items(db, **args)
                s["output"] = {"matches": [i.name for i in items]}
            if items:
                break
    return items, relaxed, args


def _recommend(ctx, parsed: dict) -> dict:
    db, state, tr = ctx["db"], ctx["state"], ctx["tracer"]
    prefs = state["prefs"]
    delta = dict(parsed.get("prefs") or {})
    state["pending"] = None  # a new search replaces any older "add it?" offer

    if parsed.get("relative_spice") and state["cart"] and ("max_spice_level" in delta):
        note = ("I can't change the spice of a single dish yet, so here are milder alternatives. ")
    else:
        note = ""
    # Standing preferences (diet, budget, spice, exclusions) persist. Request-scoped ones
    # (category, protein focus) apply only to the request that stated them, unless the
    # guest is refining the previous result ("another", "cheaper", "less spicy").
    refinement = bool(parsed.get("wants_other") or parsed.get("cheaper")
                      or (delta and set(delta) <= {"max_spice_level"}))
    if not refinement:
        for key in ("category", "protein_focus", "spice_level"):
            if key not in delta:
                prefs.pop(key, None)
    explicit = set(delta)
    if "spice_level" in delta: prefs.pop("max_spice_level", None)
    if "max_spice_level" in delta: prefs.pop("spice_level", None)
    prefs.update(delta)
    if parsed.get("exclusions"):
        prefs["exclude_ingredients"] = sorted(set(prefs.get("exclude_ingredients", [])) | set(parsed["exclusions"]))
    if parsed.get("cheaper"):
        shown = [i for i in state["last_shown"]]
        ceiling = None
        if shown:
            prices = [db.get(MenuItem, i).price for i in shown if db.get(MenuItem, i)]
            ceiling = (max(prices) - 1) if prices else None
        elif prefs.get("budget"):
            ceiling = int(prefs["budget"] * 0.8)
        if ceiling:
            prefs["budget"] = ceiling

    with tr.step("kitchen", "check_workload", {"purpose": "kitchen-aware ranking"}) as s:
        load = get_kitchen_load(db)
        s["output"] = {"level": load["level"], "wait_min": load["estimated_wait_minutes"]}
    prefer_fast = load["level"] == "busy"

    exclude = set(state["last_shown"]) if parsed.get("wants_other") else set()
    items, relaxed, used = _menu_search(ctx, prefs, exclude, prefer_fast, explicit)

    if relaxed or not items:
        with tr.step("intelligence", "log_unmet_demand", {"filters": prefs, "relaxed": relaxed}) as s:
            db.add(UnmetDemand(session_id=ctx["session_id"], query_text=ctx["message"][:500], filters=dict(prefs)))
            s["output"] = {"logged": True}

    popularity = get_dish_popularity(db)
    cards = []
    for it in items:
        reasons = get_recommendation_reasons(
            it, used.get("budget"), used.get("diet"), used.get("category"), used.get("spice_level"),
            popularity, max_spice_level=used.get("max_spice_level"),
            protein_focus=bool(used.get("protein_focus")), prefer_fast=prefer_fast,
            prep_minutes=prep_minutes_for(it))
        cards.append(_card(it, reasons))

    if not items:
        state["last_shown"] = []
        return {"reply": note + f"I couldn't find any available dish for {describe_prefs(prefs)}. "
                "I've noted this request so the restaurant can see what guests are looking for. "
                "You can say “reset my preferences” or relax a filter.", "cards": None}

    state["last_shown"] = [c["id"] for c in cards]
    lead = f"Here {'is' if len(cards)==1 else 'are'} {len(cards)} option{'s' if len(cards)>1 else ''} for {describe_prefs({**{k: v for k, v in used.items() if v}, 'exclude_ingredients': prefs.get('exclude_ingredients')})}"
    if relaxed:
        lead = f"Nothing matched all your filters, so I relaxed {', '.join(relaxed)}. " + lead
    spoken = "; ".join(f"{i+1}) {c['name']} {inr(c['price'])}" for i, c in enumerate(cards))
    extras = []
    if prefs.get("protein_focus") and any(i.protein_g is None for i in items):
        extras.append("Protein is judged from the ingredient list because exact protein values aren't recorded yet.")
    if prefer_fast:
        extras.append(f"The kitchen is busy (about {load['estimated_wait_minutes']} min wait), so I favoured quicker dishes.")
    if parsed.get("allergy") or prefs.get("exclude_ingredients"):
        extras.append("Note: I don't have verified allergen data. I only filtered by listed ingredients, so please confirm allergies with our staff.")
    if len(cards) == 1:
        state["pending"] = {"type": "offer_item", "item_id": cards[0]["id"], "quantity": 1}
        tail = " Would you like me to add it to your cart?"
    else:
        tail = " Say “add the first one”, or tell me a name."
    return {"reply": note + lead + f": {spoken}." + tail + (" " + " ".join(extras) if extras else ""), "cards": cards}


def _suggest_addon(ctx) -> str:
    """Menu agent proposes ONE relevant add-on based on the real cart and menu."""
    db, state, tr = ctx["db"], ctx["state"], ctx["tracer"]
    view = cart_view(db, state)
    categories = {l["category"] for l in view["lines"]}
    if not view["lines"] or "Drinks" in categories or state.get("pending"):
        return ""
    prefs = state["prefs"]
    remaining = None
    if prefs.get("budget") is not None:
        remaining = prefs["budget"] - view["total_amount"]
        if remaining <= 0:
            return ""
    in_cart = {l["menu_item_id"] for l in state["cart"]}
    from services.command_service import best_companion
    with tr.step("menu", "market_basket_lookup", {"cart": sorted(in_cart)}) as s:
        combo = best_companion(db, in_cart, in_cart, remaining, prefs.get("diet"))
        s["output"] = ({"companion": combo["item"].name, "confidence_pct": combo["confidence_pct"], "lift": combo["lift"]} if combo else {"companion": None, "reason": "not enough order history or no strong pair"})
    if combo:
        d = combo["item"]
        state["pending"] = {"type": "offer_item", "item_id": d.id, "quantity": 1, "addon": True}
        return (f" {combo['confidence_pct']}% of guests who ordered {combo['if_name']} also ordered {d.name} "
                f"({combo['orders_together']} of {combo['of_orders']} orders). Add {d.name} ({inr(d.price)})?")
    with tr.step("menu", "suggest_addon", {"cart_categories": sorted(categories), "remaining_budget": remaining}) as s:
        drinks = recommend_menu_items(db, budget=remaining, diet=prefs.get("diet") if prefs.get("diet") == "vegan" else None,
                                      category="Drinks", exclude_ids=in_cart, limit=1)
        s["output"] = {"suggestion": drinks[0].name if drinks else None}
    if not drinks:
        return ""
    d = drinks[0]
    state["pending"] = {"type": "offer_item", "item_id": d.id, "quantity": 1, "addon": True}
    return f" Your order has no drink yet — would you like to add {d.name} ({inr(d.price)})?"


# ---------------------------------------------------------------- Order agent
def _resolve_targets(ctx, parsed) -> tuple[list[int], str | None]:
    state, db = ctx["state"], ctx["db"]
    pending = state.get("pending") or {}
    if parsed.get("item_ids"):
        return parsed["item_ids"][:1], None
    shown = state["last_shown"]
    if parsed.get("ordinal"):
        i = parsed["ordinal"] - 1
        return ([shown[i]], None) if 0 <= i < len(shown) else ([], "I don't see that option number. Could you tell me the dish name?")
    if parsed.get("wants_all") and shown:
        return shown, None
    if pending.get("type") == "offer_item":
        return [pending["item_id"]], None
    if len(shown) == 1:
        return shown, None
    if len(shown) > 1:
        names = ", ".join(f"{i+1}) {db.get(MenuItem, x).name}" for i, x in enumerate(shown))
        return [], f"Which one would you like? {names}."
    return [], "Which dish would you like to add? Tell me a name, or ask me for recommendations."


def _order_add(ctx, parsed) -> dict:
    db, state, tr = ctx["db"], ctx["state"], ctx["tracer"]
    qty = parsed.get("quantity") or (state["pending"] or {}).get("quantity") or 1
    ids, ask = _resolve_targets(ctx, parsed)
    if ask:
        if "Which one" in ask:  # remember how many they wanted for the next message
            state["pending"] = {"type": "choose_item", "quantity": qty}
        return {"reply": ask}
    added, problems = [], []
    for item_id in ids:
        with tr.step("order", "add_to_cart", {"menu_item_id": item_id, "quantity": qty}) as s:
            try:
                # Validate the WHOLE prospective cart (availability + max items) before saving.
                prospective = [dict(l) for l in state["cart"]]
                _add_to_cart({"cart": prospective}, item_id, qty)
                priced = price_lines(db, [(l["menu_item_id"], l["quantity"]) for l in prospective])
                state["cart"] = prospective
                name = next(l["name"] for l in priced["lines"] if l["menu_item_id"] == item_id)
                added.append(f"{qty} × {name}")
                s["output"] = {"added": added[-1], "cart_total": priced["total_amount"]}
            except OrderError as exc:
                problems.append(exc.message if exc.status_code != 422 else
                                f"{exc.message}, so I didn't add that.")
                s["output"] = {"rejected": exc.message}
    state["pending"] = None
    view = cart_view(db, state)
    reply = ("Added " + " and ".join(added) + ". " if added else "") + (" ".join(problems) + " " if problems else "")
    reply += cart_text(view) if not view["lines"] else "Your cart: " + cart_text(view)
    if added:
        reply += _suggest_addon(ctx)
    return {"reply": reply.strip()}


def _order_remove(ctx, parsed) -> dict:
    state, db, tr = ctx["state"], ctx["db"], ctx["tracer"]
    cart = state["cart"]
    if not cart:
        return {"reply": "Your cart is already empty."}
    target = None
    if parsed.get("item_ids"):
        target = next((l for l in cart if l["menu_item_id"] in parsed["item_ids"]), None)
    elif parsed.get("ordinal") and 0 < parsed["ordinal"] <= len(cart):
        target = cart[parsed["ordinal"] - 1]
    elif parsed.get("last") or len(cart) == 1:
        target = cart[-1]
    if target is None:
        return {"reply": "Which item should I remove? " + cart_text(cart_view(db, state))}
    name = db.get(MenuItem, target["menu_item_id"]).name
    with tr.step("order", "remove_from_cart", {"menu_item_id": target["menu_item_id"]}) as s:
        cart.remove(target)
        s["output"] = {"removed": name}
    state["pending"] = None
    return {"reply": f"Removed {name}. " + cart_text(cart_view(db, state))}


def _order_set_qty(ctx, parsed) -> dict:
    state, db, tr = ctx["state"], ctx["db"], ctx["tracer"]
    if not state["cart"]:
        return {"reply": "Your cart is empty, so there's nothing to change yet."}
    target = next((l for l in state["cart"] if l["menu_item_id"] in (parsed.get("item_ids") or [])), state["cart"][-1])
    with tr.step("order", "set_quantity", {"menu_item_id": target["menu_item_id"], "quantity": parsed["quantity"]}) as s:
        target["quantity"] = parsed["quantity"]
        s["output"] = {"quantity": parsed["quantity"]}
    name = db.get(MenuItem, target["menu_item_id"]).name
    return {"reply": f"Updated {name} to {parsed['quantity']}. " + cart_text(cart_view(db, state))}


def _checkout(ctx) -> dict:
    db, state, tr = ctx["db"], ctx["state"], ctx["tracer"]
    view = cart_view(db, state)
    if not view["lines"]:
        extra = f" ({', '.join(view['removed'])} became unavailable and was removed.)" if view["removed"] else ""
        return {"reply": "Your cart is empty. Tell me what you'd like and I'll add it." + extra}
    if not state.get("customer_name"):
        state["pending"] = {"type": "ask_name"}
        return {"reply": "Happy to place that. What name should I put the order under?"}
    with tr.step("kitchen", "estimate_ready_time", {"cart_items": view["total_items"]}) as s:
        load = get_kitchen_load(db, [(l["menu_item_id"], l["quantity"]) for l in view["lines"]])
        s["output"] = {"estimated_ready_minutes": load["estimated_ready_minutes"], "level": load["level"]}
    state["pending"] = {"type": "confirm_order"}
    meta = state.get("order_meta") or {}
    where = "Dine-in" + (f", table {meta['table_number']}" if meta.get("table_number") else "") if meta.get("order_type") == "dine_in" else "Takeaway"
    where += f" · note: {meta['notes']}" if meta.get("notes") else ""
    removed = f" Note: {', '.join(view['removed'])} became unavailable and was removed. " if view["removed"] else " "
    return {"reply": f"Please confirm your order for {state['customer_name']}: {cart_text(view)}{removed}"
                     f"{where}. Estimated ready in about {load['estimated_ready_minutes']} minutes (an estimate). "
                     "Shall I place it? (yes / no)", "kitchen": load}


def _provide_name(ctx, parsed) -> dict:
    raw = re.sub(r"^(my name is|i am|i'm|it's|its|this is|name is|mera naam|naam)\s+", "", parsed["text"]).strip(" .!")
    if not re.fullmatch(r"[a-zA-Z][a-zA-Z .'-]{1,59}", raw):
        return {"reply": "Sorry, I didn't catch a valid name. Please type just your name (letters only)."}
    ctx["state"]["customer_name"] = raw.title()
    ctx["state"]["pending"] = None
    return _checkout(ctx)


def _place_order(ctx) -> dict:
    db, state, tr = ctx["db"], ctx["state"], ctx["tracer"]
    view = cart_view(db, state)
    if not view["lines"]:
        state["pending"] = None
        return {"reply": "Your cart is empty, so I haven't placed anything."}
    with tr.step("order", "place_order", {"customer": state["customer_name"], "lines": len(view["lines"])}) as s:
        try:
            meta = state.get("order_meta") or {}
            order = create_order(db, state["customer_name"], [(l["menu_item_id"], l["quantity"]) for l in view["lines"]],
                                 source="chat", session_id=ctx["session_id"], order_type=meta.get("order_type", "takeaway"),
                                 table_number=meta.get("table_number"), notes=meta.get("notes"))
        except OrderError as exc:
            state["pending"] = None
            s["output"] = {"rejected": exc.message}
            return {"reply": f"I couldn't place the order: {exc.message}. Nothing was saved; your cart is unchanged."}
        s["output"] = {"order_id": order.id, "total": order.total_amount, "tracking_code": order.tracking_code, "eta_minutes": order.eta_minutes}
    with tr.step("kitchen", "queue_order", {"order_id": order.id}) as s:
        load = get_kitchen_load(db)
        s["output"] = {"estimated_wait_minutes": load["estimated_wait_minutes"]}
    state["last_order_lines"] = [{"menu_item_id": l["menu_item_id"], "quantity": l["quantity"]} for l in view["lines"]]
    state["cart"], state["pending"], state["last_order_id"] = [], None, order.id
    state["order_meta"] = {**(state.get("order_meta") or {}), "notes": None}
    return {"reply": f"Order #{order.id} is placed for {state['customer_name']}. Total {inr(order.total_amount)} (calculated by our system). "
                     f"Estimated ready in about {order.eta_minutes} minutes (an estimate). Track it live with code {order.tracking_code}.",
            "order": {"id": order.id, "total_amount": order.total_amount, "status": order.status,
                      "tracking_code": order.tracking_code, "eta_minutes": order.eta_minutes}, "kitchen": load}


def _decline(ctx) -> dict:
    p = (ctx["state"].get("pending") or {}).get("type")
    ctx["state"]["pending"] = None
    if p == "confirm_cancel":
        return {"reply": "Okay, I've left your order as it is."}
    if p == "offer_item":
        return {"reply": "No problem. What else can I help you with?"}
    return {"reply": "Okay, I haven't placed any order. Your cart is saved — say “place my order” when you're ready, or tell me what to change."}


def _cancel_order(ctx) -> dict:
    db, state = ctx["db"], ctx["state"]
    oid = state.get("last_order_id")
    order = db.get(Order, oid) if oid else None
    if order is None:
        return {"reply": "I don't see an order placed in this chat. Your cart can be emptied by saying “clear my cart”."}
    if order.status != "pending":
        return {"reply": f"Order #{order.id} is already {order.status}, so it can no longer be cancelled here. Please speak to our staff."}
    state["pending"] = {"type": "confirm_cancel", "order_id": order.id}
    return {"reply": f"Do you want to cancel order #{order.id} ({inr(order.total_amount)})? (yes / no)"}


def _confirm_yes(ctx, parsed) -> dict:
    state, db = ctx["state"], ctx["db"]
    p = state.get("pending") or {}
    if p.get("type") == "confirm_order":
        return _place_order(ctx)
    if p.get("type") == "offer_item":
        return _order_add(ctx, {"item_ids": [p["item_id"]], "quantity": p.get("quantity", 1)})
    if p.get("type") == "confirm_cancel":
        order = db.get(Order, p["order_id"])
        state["pending"] = None
        if order and order.status == "pending":
            with ctx["tracer"].step("order", "cancel_order", {"order_id": order.id}) as s:
                set_status(db, order, "cancelled")
                s["output"] = {"status": "cancelled", "stock_restored": True}
            return {"reply": f"Order #{order.id} has been cancelled."}
        return {"reply": "That order can no longer be cancelled."}
    return {"reply": "Sure! " + CAPABILITIES}


# ---------------------------------------------------------------- Kitchen / Intelligence
def _kitchen_status(ctx) -> dict:
    with ctx["tracer"].step("kitchen", "check_workload") as s:
        load = get_kitchen_load(ctx["db"])
        s["output"] = {"level": load["level"], "wait_min": load["estimated_wait_minutes"]}
    word = {"light": "quiet", "moderate": "moderately busy", "busy": "busy"}[load["level"]]
    return {"reply": f"The kitchen is {word} right now: {load['active_orders']} active order{'s' if load['active_orders'] != 1 else ''}, about "
                     f"{load['estimated_wait_minutes']} minutes before a new order starts" + (f"; {load['late_orders']} running late" if load.get("late_orders") else "") + ". This is an estimate.", "kitchen": load}


def _order_status(ctx) -> dict:
    """Order Tracking Agent: real minutes-left from timestamps and the promised ETA."""
    db, state = ctx["db"], ctx["state"]
    order = db.get(Order, state["last_order_id"]) if state.get("last_order_id") else None
    if order is None:
        return {"reply": "I don't see an order placed in this chat yet."}
    with ctx["tracer"].step("tracking", "lookup_tracking", {"order_id": order.id}) as s:
        t = get_tracking(db, order)
        s["output"] = {"status": t["status"], "state": t["state"], "remaining_seconds": t["remaining_seconds"], "orders_ahead": t["orders_ahead"]}
    return {"reply": f"Order #{order.id}: {t['message']}", "tracking": t,
            "order": {"id": order.id, "status": order.status, "total_amount": order.total_amount,
                      "tracking_code": order.tracking_code, "eta_minutes": order.eta_minutes}}


def _set_order_type(ctx, parsed) -> dict:
    meta = ctx["state"].setdefault("order_meta", {"order_type": "takeaway", "table_number": None, "notes": None})
    with ctx["tracer"].step("order", "set_order_type", {"order_type": parsed["order_type"], "table": parsed.get("table_number")}) as s:
        meta["order_type"] = parsed["order_type"]
        meta["table_number"] = parsed.get("table_number") if parsed["order_type"] == "dine_in" else None
        s["output"] = dict(meta)
    if parsed["order_type"] == "dine_in":
        tail = f"Dine-in at table {meta['table_number']}." if meta["table_number"] else "Dine-in. Tell me your table number (e.g. “table 4”) so we can bring it over."
    else:
        tail = "Takeaway — we'll have it packed for pickup."
    return {"reply": tail + " Say “place my order” when you're ready."}


def _add_note(ctx, parsed) -> dict:
    note = parsed["note"][:200]
    with ctx["tracer"].step("order", "add_note", {"note": note}) as s:
        ctx["state"].setdefault("order_meta", {})["notes"] = note
        s["output"] = {"saved": True}
    return {"reply": f"Noted for the kitchen: “{note}”. This is passed on as written; the kitchen decides what's possible."}


def _reorder(ctx) -> dict:
    state, tr = ctx["state"], ctx["tracer"]
    lines = state.get("last_order_lines") or []
    if not lines:
        return {"reply": "I don't have a previous order from this chat to repeat. Tell me what you'd like."}
    added, problems = [], []
    for line in lines:
        with tr.step("order", "add_to_cart", {"menu_item_id": line["menu_item_id"], "quantity": line["quantity"], "reorder": True}) as s:
            try:
                prospective = [dict(l) for l in state["cart"]]
                _add_to_cart({"cart": prospective}, line["menu_item_id"], line["quantity"])
                priced = price_lines(ctx["db"], [(l["menu_item_id"], l["quantity"]) for l in prospective])
                state["cart"] = prospective
                name = next(l["name"] for l in priced["lines"] if l["menu_item_id"] == line["menu_item_id"])
                added.append(f"{line['quantity']} × {name}")
                s["output"] = {"added": added[-1]}
            except OrderError as exc:
                problems.append(exc.message)
                s["output"] = {"rejected": exc.message}
    state["pending"] = None
    view = cart_view(ctx["db"], state)
    reply = ("Added your previous order. " if added else "") + (" ".join(problems) + " " if problems else "")
    return {"reply": (reply + cart_text(view) + " Say “place my order” to confirm.").strip()}


def _give_feedback(ctx, parsed) -> dict:
    db, state = ctx["db"], ctx["state"]
    order = db.get(Order, state["last_order_id"]) if state.get("last_order_id") else None
    if order is None:
        return {"reply": "I can take feedback once you've placed an order in this chat."}
    with ctx["tracer"].step("feedback", "save_feedback", {"order_id": order.id, "rating": parsed["rating"]}) as s:
        try:
            row = submit_feedback(db, order, parsed["rating"], parsed.get("comment"))
        except OrderError as exc:
            s["output"] = {"rejected": exc.message}
            return {"reply": exc.message}
        s["output"] = {"sentiment": row.sentiment, "topics": row.topics, "flagged_for_follow_up": not row.resolved}
    return {"reply": recovery_message(parsed["rating"])}


def _feedback_summary(ctx) -> dict:
    if ctx["role"] != "owner":
        return {"reply": "Guest feedback summaries are available to restaurant staff only. You can rate your own order by saying, for example, “rate 5 stars, loved it”."}
    from services.ops_service import feedback_summary
    with ctx["tracer"].step("feedback", "summarise_feedback") as s:
        fb = feedback_summary(ctx["db"])
        s["output"] = {"count": fb["count"], "average": fb["average"], "follow_up": fb["needs_follow_up"]}
    if not fb["count"]:
        return {"reply": "No guest feedback has been recorded yet."}
    top = fb["top_complaints"][0] if fb["top_complaints"] else None
    return {"reply": f"{fb['count']} rating(s), average {fb['average']}/5; {fb['needs_follow_up']} need follow-up." +
                     (f" Top complaint: {top['topic']} ({top['count']}×)." if top else ""), "feedback": fb}


def _inventory(ctx) -> dict:
    if ctx["role"] != "owner":
        return {"reply": "Inventory details are available to restaurant staff only. I can tell you if a specific dish is available."}
    from services.ops_service import inventory_summary
    with ctx["tracer"].step("inventory", "check_stock_levels") as s:
        inv = inventory_summary(ctx["db"])
        s["output"] = {"low": len(inv["low_stock"]), "sold_out": len(inv["sold_out"]), "tracked": inv["tracked"]}
    if not inv["tracked"]:
        return {"reply": "Stock tracking isn't switched on for any dish yet. Set a stock quantity on a dish (owner panel) and I'll warn you when it runs low.", "inventory": inv}
    parts = [f"{len(inv['sold_out'])} sold out" if inv["sold_out"] else None, f"{len(inv['low_stock'])} running low" if inv["low_stock"] else None]
    names = ", ".join(f"{m['name']} ({m['stock']})" for m in (inv["sold_out"] + inv["low_stock"])[:5])
    return {"reply": f"Tracking stock for {inv['tracked']} dish{'es' if inv['tracked'] != 1 else ''}. " + (" and ".join(p for p in parts if p) + f": {names}." if any(parts) else "Nothing is running low."), "inventory": inv}


def _analytics(ctx) -> dict:
    if ctx["role"] != "owner":
        return {"reply": "Business analytics is available to restaurant staff only. I can help with the menu, your order, or kitchen wait times."}
    from services.copilot_service import answer as copilot_answer
    with ctx["tracer"].step("intelligence", "answer_business_question", {"question": ctx["message"]}) as s:
        ans = copilot_answer(ctx["db"], ctx["message"])
        s["output"] = {"intent": ans["intent"], "period": ans["period"], "basis": ans["basis"]}
    if ans["intent"] != "help":
        return {"reply": ans["answer"], "copilot": ans}
    from services.insights_service import build_insights
    with ctx["tracer"].step("intelligence", "build_insights", {"source": "SQL over orders and unmet_demand"}) as s:
        data = build_insights(ctx["db"])
        s["output"] = {"sufficient_data": data["data_sufficiency"]["sufficient"], "insights": len(data["insights"])}
    lines = [i["text"] for i in data["insights"][:4]] or ["There is not enough data yet for insights."]
    return {"reply": " ".join(lines), "insights": data}


def _show_item(ctx, parsed) -> dict:
    db, state = ctx["db"], ctx["state"]
    item = db.get(MenuItem, parsed["item_ids"][0])
    if not item.available:
        return {"reply": f"{item.name} is currently unavailable."}
    state["last_shown"] = [item.id]
    state["pending"] = {"type": "offer_item", "item_id": item.id, "quantity": 1}
    ing = ", ".join(item.ingredients or [])
    return {"reply": f"{item.name} — {inr(item.price)}, {item.spice_level} spice. {item.description} Ingredients: {ing}. Add it to your cart?",
            "cards": [_card(item, ["You asked about this dish"])]}


# ---------------------------------------------------------------- entry point
def handle_message(db: Session, session_id: str | None, message: str, role: str = "customer") -> dict:
    session_id = normalize_session_id(session_id)
    tracer = Tracer(session_id, message)
    row, state = load_session(db, session_id)
    ctx = {"db": db, "state": state, "tracer": tracer, "session_id": session_id, "role": role, "message": message}
    extra: dict = {}
    intent = None
    try:
        menu = _menu_snapshot(db)
        with tracer.step("supervisor", "classify_intent", {"message": message}) as s:
            parsed = nlu.parse_message(message, state, menu, _vocab(menu))
            intent = parsed["intent"]
            s["output"] = {"intent": intent, "route": ROUTES.get(intent, "supervisor (answered directly)"),
                           "pending": (state.get("pending") or {}).get("type")}
        state["turns"] += 1

        handlers = {
            "recommend": lambda: _recommend(ctx, parsed), "show_item": lambda: _show_item(ctx, parsed),
            "add_item": lambda: _order_add(ctx, parsed), "remove_item": lambda: _order_remove(ctx, parsed),
            "set_quantity": lambda: _order_set_qty(ctx, parsed),
            "show_cart": lambda: {"reply": cart_text(cart_view(db, state))},
            "clear_cart": lambda: (state.update(cart=[], pending=None) or {"reply": "I've emptied your cart."}),
            "checkout": lambda: _checkout(ctx), "provide_name": lambda: _provide_name(ctx, parsed),
            "confirm_yes": lambda: _confirm_yes(ctx, parsed), "decline": lambda: _decline(ctx),
            "modify_order": lambda: (state.update(pending=None) or {"reply": "Of course — nothing has been placed. " + cart_text(cart_view(db, state)) + " Tell me what to add, remove or change."}),
            "cancel_order": lambda: _cancel_order(ctx), "order_status": lambda: _order_status(ctx),
            "set_order_type": lambda: _set_order_type(ctx, parsed), "add_note": lambda: _add_note(ctx, parsed),
            "reorder": lambda: _reorder(ctx), "give_feedback": lambda: _give_feedback(ctx, parsed),
            "feedback_summary": lambda: _feedback_summary(ctx), "inventory": lambda: _inventory(ctx),
            "kitchen_status": lambda: _kitchen_status(ctx), "analytics": lambda: _analytics(ctx),
            "reset_prefs": lambda: (state.update(prefs={}, last_shown=[], pending=None) or {"reply": "Done — I've cleared your preferences. What are you in the mood for?"}),
            "greet": lambda: {"reply": "Welcome to TasteFlow Bistro! " + CAPABILITIES},
            "help": lambda: {"reply": CAPABILITIES},
            "empty": lambda: {"reply": "I didn't catch that. " + CAPABILITIES},
            "yes_no_context": lambda: {"reply": "Sure! " + CAPABILITIES},
        }
        outcome = handlers.get(intent, lambda: {"reply": "I'm not sure I understood. " + CAPABILITIES})()
        if intent != "add_item" and (state.get("pending") or {}).get("type") == "choose_item":
            state["pending"] = None  # a stale "which one?" must not hijack later messages
        reply, extra = outcome["reply"], outcome
        view = cart_view(db, state)
        save_session(db, row, state)
        trace = tracer.finish(db, intent, reply)
        db.commit()
    except Exception:  # noqa: BLE001
        log.exception("agent run failed")
        db.rollback()
        reply = "Sorry — something went wrong on our side. Nothing was changed; please try again."
        trace = tracer.finish(db, intent, reply, status="error")
        db.commit()
        view = {"lines": [], "total_items": 0, "total_amount": 0}
        extra = {}

    return {
        "session_id": session_id,
        "reply": reply,
        "intent": intent,
        "agents_used": [{"id": a, "label": AGENT_LABELS[a]} for a in tracer.agents_used],
        "cards": extra.get("cards"),
        "cart": view,
        "pending": state.get("pending"),
        "order": extra.get("order"),
        "kitchen": extra.get("kitchen"),
        "tracking": extra.get("tracking"),
        "copilot": extra.get("copilot"),
        "order_meta": state.get("order_meta"),
        "prefs": state.get("prefs", {}),
        "trace": trace,
    }
