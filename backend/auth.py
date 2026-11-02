"""Role-based staff login using signed, expiring tokens (stdlib only).

Customers need no login. Owner and kitchen staff log in with a PIN and get a
token that the frontend sends as `Authorization: Bearer <token>`.
Simple on purpose: easy to explain, and every protected route uses the
same `require_role(...)` dependency.
"""
import base64
import hashlib
import hmac
import json
import time

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

import config

router = APIRouter(prefix="/api/auth", tags=["Auth"])

ROLES = {"owner", "kitchen"}


def _sign(payload_b64: str) -> str:
    return hmac.new(config.AUTH_SECRET.encode(), payload_b64.encode(),
                    hashlib.sha256).hexdigest()


def create_token(role: str) -> str:
    payload = {"role": role, "exp": int(time.time()) + config.TOKEN_TTL_SECONDS}
    payload_b64 = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()
    return f"{payload_b64}.{_sign(payload_b64)}"


def verify_token(token: str) -> dict | None:
    try:
        payload_b64, signature = token.split(".", 1)
        if not hmac.compare_digest(signature, _sign(payload_b64)):
            return None
        payload = json.loads(base64.urlsafe_b64decode(payload_b64.encode()))
        if payload.get("exp", 0) < time.time() or payload.get("role") not in ROLES:
            return None
        return payload
    except Exception:
        return None


def require_role(*allowed: str):
    """FastAPI dependency. The owner may do everything the kitchen can."""
    accepted = set(allowed) | {"owner"}

    def dependency(authorization: str | None = Header(default=None)) -> str:
        if not authorization or not authorization.lower().startswith("bearer "):
            raise HTTPException(401, "Login required")
        payload = verify_token(authorization[7:].strip())
        if payload is None:
            raise HTTPException(401, "Session expired or invalid. Please log in again.")
        if payload["role"] not in accepted:
            raise HTTPException(403, "You do not have access to this area")
        return payload["role"]

    return dependency


class LoginRequest(BaseModel):
    role: str = Field(pattern="^(owner|kitchen)$")
    pin: str = Field(min_length=1, max_length=100)


@router.post("/login")
def login(body: LoginRequest):
    expected = config.OWNER_PIN if body.role == "owner" else config.KITCHEN_PIN
    if not hmac.compare_digest(body.pin, expected):
        raise HTTPException(401, "Incorrect PIN")
    return {"token": create_token(body.role), "role": body.role,
            "expires_in": config.TOKEN_TTL_SECONDS}


@router.get("/me")
def me(role: str = Depends(require_role("kitchen"))):
    return {"role": role}
