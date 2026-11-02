"""Shared conversation state. Stored as JSON in chat_sessions so every agent
sees the same memory and a customer never has to repeat themselves."""
import copy
import re
import uuid
from datetime import datetime

from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from models import ChatSession

SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")


def new_state() -> dict:
    return {
        "prefs": {},            # diet, budget, category, spice_level, max_spice_level, protein_focus, exclude_ingredients
        "cart": [],             # [{"menu_item_id": int, "quantity": int}]
        "last_shown": [],       # dish ids shown in the last recommendation
        "pending": None,        # {"type": "ask_name"|"confirm_order"|"offer_item"|"confirm_cancel", ...}
        "customer_name": None,
        "last_order_id": None,
        "last_order_lines": [],  # for "order the same again"
        "order_meta": {"order_type": "takeaway", "table_number": None, "notes": None},
        "turns": 0,
    }


def normalize_session_id(session_id: str | None) -> str:
    if session_id and SESSION_ID_RE.match(session_id):
        return session_id
    return uuid.uuid4().hex


def load_session(db: Session, session_id: str) -> tuple[ChatSession, dict]:
    row = db.get(ChatSession, session_id)
    if row is None:
        row = ChatSession(id=session_id, state=new_state())
        db.add(row)
        db.flush()
    state = {**new_state(), **copy.deepcopy(row.state or {})}
    return row, state


def save_session(db: Session, row: ChatSession, state: dict) -> None:
    row.state = copy.deepcopy(state)
    row.updated_at = datetime.utcnow()
    flag_modified(row, "state")
