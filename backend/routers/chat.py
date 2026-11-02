from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from agents.orchestrator import AGENT_LABELS, handle_message
from agents.state import load_session, new_state, normalize_session_id, save_session
from auth import require_role, verify_token
from database import get_db
from models import AgentRun, AgentStep

router = APIRouter(prefix="/api", tags=["Multi-Agent Chat"])


class ChatRequest(BaseModel):
    session_id: str | None = None
    message: str = Field(min_length=1, max_length=1000)

    @field_validator("message")
    @classmethod
    def not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Message cannot be empty")
        return v


class ResetRequest(BaseModel):
    session_id: str


def _optional_role(authorization: str | None) -> str:
    if authorization and authorization.lower().startswith("bearer "):
        payload = verify_token(authorization[7:].strip())
        if payload:
            return payload["role"]
    return "customer"


@router.post("/chat")
def chat(body: ChatRequest, db: Session = Depends(get_db), authorization: str | None = Header(default=None)):
    """Customers chat freely. A valid owner token additionally unlocks analytics."""
    return handle_message(db, body.session_id, body.message, role=_optional_role(authorization))


@router.post("/chat/reset")
def reset_chat(body: ResetRequest, db: Session = Depends(get_db)):
    session_id = normalize_session_id(body.session_id)
    row, _ = load_session(db, session_id)
    save_session(db, row, new_state())
    db.commit()
    return {"session_id": session_id, "reset": True}


@router.get("/agents/registry")
def agent_registry():
    """What each agent is responsible for and which backend tools it may use."""
    return {"agents": [
        {"id": "supervisor", "label": AGENT_LABELS["supervisor"], "role": "Understands intent, routes, keeps shared state",
         "tools": ["classify_intent"]},
        {"id": "menu", "label": AGENT_LABELS["menu"], "role": "Searches the real menu, explains matches, suggests add-ons",
         "tools": ["search_menu", "relax_search", "suggest_addon"]},
        {"id": "order", "label": AGENT_LABELS["order"], "role": "Builds the cart, asks for confirmation, saves the order via the backend",
         "tools": ["add_to_cart", "remove_from_cart", "set_quantity", "set_order_type", "add_note", "place_order", "cancel_order"]},
        {"id": "kitchen", "label": AGENT_LABELS["kitchen"], "role": "Estimates kitchen workload and ready time",
         "tools": ["check_workload", "estimate_ready_time", "queue_order", "lookup_order"]},
        {"id": "intelligence", "label": AGENT_LABELS["intelligence"], "role": "Logs unmet demand and produces data-backed insights (staff only)",
         "tools": ["log_unmet_demand", "build_insights"]},
        {"id": "tracking", "label": AGENT_LABELS["tracking"], "role": "Answers 'how many minutes left?' from real timestamps and the promised ETA",
         "tools": ["lookup_tracking"]},
        {"id": "feedback", "label": AGENT_LABELS["feedback"], "role": "Collects ratings, finds complaint topics, flags low scores for follow-up",
         "tools": ["save_feedback", "summarise_feedback"]},
        {"id": "inventory", "label": AGENT_LABELS["inventory"], "role": "Watches tracked stock, hides sold-out dishes, warns when running low (staff only)",
         "tools": ["check_stock_levels"]},
    ], "guarantees": ["Prices, totals, availability and order saving are computed by backend code, never by the model",
                      "An order is reported as placed only after the database confirms it"]}


@router.get("/agents/runs", dependencies=[Depends(require_role("owner"))])
def agent_runs(limit: int = 20, db: Session = Depends(get_db)):
    """Recent agent runs with every step (owner only)."""
    limit = max(1, min(limit, 100))
    runs = db.query(AgentRun).order_by(AgentRun.id.desc()).limit(limit).all()
    steps = db.query(AgentStep).filter(AgentStep.run_id.in_([r.id for r in runs])).order_by(AgentStep.run_id, AgentStep.seq).all() if runs else []
    by_run: dict[int, list] = {}
    for s in steps:
        by_run.setdefault(s.run_id, []).append({"seq": s.seq, "agent": s.agent, "action": s.action, "input": s.input,
                                                "output": s.output, "ok": s.ok, "duration_ms": s.duration_ms})
    return [{"run_id": r.id, "session_id": r.session_id[:8], "message": r.user_message, "intent": r.intent,
             "reply": r.final_reply, "status": r.status, "duration_ms": r.duration_ms,
             "created_at": r.created_at.isoformat() + "Z", "steps": by_run.get(r.id, [])} for r in runs]
