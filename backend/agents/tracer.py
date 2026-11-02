"""Agent transparency: records every agent action so the UI can show who did
what, with which tool, what came back, and how long it took."""
import time
from contextlib import contextmanager

from sqlalchemy.orm import Session

from models import AgentRun, AgentStep


def _shrink(value, depth=0):
    """Keep trace payloads small and JSON-safe."""
    if isinstance(value, dict):
        return {str(k): _shrink(v, depth + 1) for k, v in list(value.items())[:15]}
    if isinstance(value, (list, tuple, set)):
        items = list(value)
        return [_shrink(v, depth + 1) for v in items[:8]] + (["…"] if len(items) > 8 else [])
    if isinstance(value, str):
        return value if len(value) <= 160 else value[:157] + "…"
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return str(value)


class Tracer:
    def __init__(self, session_id: str, message: str):
        self.session_id = session_id
        self.message = message
        self.steps: list[dict] = []
        self._start = time.perf_counter()

    @contextmanager
    def step(self, agent: str, action: str, input=None):
        record = {"seq": len(self.steps) + 1, "agent": agent, "action": action,
                  "input": _shrink(input), "output": None, "ok": True, "duration_ms": 0}
        self.steps.append(record)
        t0 = time.perf_counter()
        holder = {}
        try:
            yield holder
        except Exception as exc:  # noqa: BLE001 - recorded, then re-raised
            record["ok"] = False
            record["output"] = {"error": type(exc).__name__}
            raise
        finally:
            record["duration_ms"] = round((time.perf_counter() - t0) * 1000)
            if record["ok"]:
                record["output"] = _shrink(holder.get("output"))

    @property
    def agents_used(self) -> list[str]:
        seen: list[str] = []
        for s in self.steps:
            if s["agent"] not in seen:
                seen.append(s["agent"])
        return seen

    def finish(self, db: Session, intent: str | None, reply: str, status: str = "ok") -> dict:
        duration = round((time.perf_counter() - self._start) * 1000)
        run = AgentRun(session_id=self.session_id, user_message=self.message[:1000],
                       intent=intent, final_reply=reply[:2000], status=status,
                       duration_ms=duration)
        db.add(run)
        db.flush()
        for s in self.steps:
            db.add(AgentStep(run_id=run.id, seq=s["seq"], agent=s["agent"], action=s["action"],
                             input=s["input"], output=s["output"], ok=s["ok"],
                             duration_ms=s["duration_ms"]))
        return {"run_id": run.id, "duration_ms": duration, "steps": self.steps}
