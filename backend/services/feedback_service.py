"""Feedback & Service Recovery: store ratings, find what went wrong, flag follow-ups.
Topic detection is plain keyword matching, so it is transparent and testable."""
from sqlalchemy.orm import Session

from models import Feedback, Order
from services.order_service import OrderError

NEGATIVE_TOPICS = {
    "wait time": ("late", "slow", "wait", "waiting", "delay", "long time", "took forever"),
    "temperature": ("cold", "lukewarm", "not hot", "thanda"),
    "taste": ("bland", "salty", "tasteless", "oily", "stale", "bad taste", "undercooked", "burnt"),
    "service": ("rude", "ignored", "unhelpful", "staff"),
    "order accuracy": ("wrong", "missing", "forgot", "incorrect"),
}
PRAISE = ("delicious", "tasty", "great", "amazing", "love", "fresh", "excellent", "perfect", "yummy")


def analyze(rating: int, comment: str | None) -> tuple[str, list[str]]:
    text = (comment or "").lower()
    sentiment = "positive" if rating >= 4 else "negative" if rating <= 2 else "neutral"
    topics = [t for t, words in NEGATIVE_TOPICS.items() if any(w in text for w in words)] if rating <= 3 else []
    if rating >= 4 and any(w in text for w in PRAISE):
        topics = ["praise"]
    return sentiment, topics


def submit_feedback(db: Session, order: Order, rating: int, comment: str | None) -> Feedback:
    if order.status not in ("ready", "completed"):
        raise OrderError(409, "You can rate an order once it is ready.")
    if db.query(Feedback.id).filter(Feedback.order_id == order.id).first():
        raise OrderError(409, "This order has already been rated. Thank you!")
    sentiment, topics = analyze(rating, comment)
    row = Feedback(order_id=order.id, rating=rating, comment=(comment or "").strip()[:500] or None,
                   sentiment=sentiment, topics=topics, resolved=rating > 2)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def recovery_message(rating: int) -> str:
    if rating <= 2:
        return ("I'm sorry we missed the mark. Your feedback has been flagged for the restaurant manager to follow up on.")
    if rating == 3:
        return "Thanks for the honest feedback. We'll use it to improve."
    return "Thank you! We're glad you enjoyed it."
