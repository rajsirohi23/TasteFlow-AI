
from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
)

from database import Base


class MenuItem(Base):
    __tablename__ = "menu_items"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(120), nullable=False, index=True)
    price = Column(Integer, nullable=False)
    category = Column(String(80), nullable=False, index=True)

    dietary_tags = Column(JSON, nullable=False, default=list)
    ingredients = Column(JSON, nullable=False, default=list)

    description = Column(Text, nullable=False)
    spice_level = Column(String(30), nullable=False)
    available = Column(Boolean, nullable=False, default=True)

    image = Column(String(1000), nullable=False)

    # Optional operational data. NULL means "we do not have this information";
    # the system never invents values for these.
    protein_g = Column(Integer, nullable=True)
    calories = Column(Integer, nullable=True)
    nutrition_source = Column(String(20), nullable=True)  # "verified" | "estimate"
    prep_minutes = Column(Integer, nullable=True)
    # NULL = stock not tracked. A number is decremented by every order and restored on cancel.
    stock_quantity = Column(Integer, nullable=True)
    cost_price = Column(Integer, nullable=True)  # optional: unlocks true margin analysis
    archived = Column(Boolean, nullable=False, default=False)  # removed from the menu but kept for order history


class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, index=True)
    customer_name = Column(String(120), nullable=False)
    status = Column(String(30), nullable=False, default="pending")
    total_amount = Column(Integer, nullable=False)
    created_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
    )

    # Where the order came from and whether it is demo data.
    source = Column(String(20), nullable=False, default="web")  # web | chat | voice
    session_id = Column(String(64), nullable=True, index=True)
    is_demo = Column(Boolean, nullable=False, default=False)

    # Tracking and service details.
    tracking_code = Column(String(12), nullable=True, index=True)
    eta_minutes = Column(Integer, nullable=True)          # promised at placement (an estimate)
    order_type = Column(String(12), nullable=False, default="takeaway")  # takeaway | dine_in
    table_number = Column(String(10), nullable=True)
    notes = Column(String(300), nullable=True)


class OrderItem(Base):
    __tablename__ = "order_items"

    id = Column(Integer, primary_key=True, index=True)

    order_id = Column(
        Integer,
        ForeignKey("orders.id"),
        nullable=False,
        index=True,
    )

    menu_item_id = Column(
        Integer,
        ForeignKey("menu_items.id"),
        nullable=False,
    )

    quantity = Column(Integer, nullable=False)
    unit_price = Column(Integer, nullable=False)



class ChatSession(Base):
    """Server-side conversation memory shared by all agents."""
    __tablename__ = "chat_sessions"

    id = Column(String(64), primary_key=True)
    state = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class AgentRun(Base):
    """One customer message handled by the multi-agent system."""
    __tablename__ = "agent_runs"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(String(64), nullable=False, index=True)
    user_message = Column(Text, nullable=False)
    intent = Column(String(40), nullable=True)
    final_reply = Column(Text, nullable=True)
    status = Column(String(20), nullable=False, default="ok")  # ok | error
    duration_ms = Column(Integer, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)


class AgentStep(Base):
    """One agent action (tool call or decision) inside a run."""
    __tablename__ = "agent_steps"

    id = Column(Integer, primary_key=True, index=True)
    run_id = Column(Integer, ForeignKey("agent_runs.id"), nullable=False, index=True)
    seq = Column(Integer, nullable=False)
    agent = Column(String(30), nullable=False)
    action = Column(String(60), nullable=False)
    input = Column(JSON, nullable=True)
    output = Column(JSON, nullable=True)
    ok = Column(Boolean, nullable=False, default=True)
    duration_ms = Column(Integer, nullable=True)


class UnmetDemand(Base):
    """Something a customer asked for that the menu could not satisfy."""
    __tablename__ = "unmet_demand"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(String(64), nullable=True)
    query_text = Column(Text, nullable=False)
    filters = Column(JSON, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)


class OrderStatusEvent(Base):
    """Every status change with its timestamp: the source of real timing data."""
    __tablename__ = "order_status_events"

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False, index=True)
    status = Column(String(20), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class Feedback(Base):
    """Guest rating for an order, with a simple topic analysis and a follow-up flag."""
    __tablename__ = "feedback"

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False, index=True)
    rating = Column(Integer, nullable=False)
    comment = Column(String(500), nullable=True)
    sentiment = Column(String(10), nullable=False)       # positive | neutral | negative
    topics = Column(JSON, nullable=True)                 # e.g. ["wait time", "temperature"]
    resolved = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
