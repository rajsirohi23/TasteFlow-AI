"""Test helpers.

1. ISOLATION: the app's global session factory is re-bound to an in-memory
   database seeded from frontend/data/menu-demo.json BEFORE any test module is
   imported. Tests can therefore never read or modify the real tasteflow.db,
   and they pass identically on every machine.
2. AUTH: staff routes need a login token. For readability the original tests
   send an OWNER token by default; security tests pass an explicit
   `headers={"Authorization": ""}` (anonymous) or their own token.
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

import database
from auth import create_token
from database import Base
from init_db import load_demo_menu
from models import MenuItem

_engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
Base.metadata.create_all(bind=_engine)
database.SessionLocal.configure(bind=_engine)
with database.SessionLocal() as _db:
    _db.add_all(MenuItem(**row) for row in load_demo_menu())
    _db.commit()


@pytest.fixture(autouse=True)
def _default_owner_auth(monkeypatch):
    original = TestClient.request

    def request(self, method, url, **kwargs):
        headers = dict(kwargs.get("headers") or {})
        if not any(k.lower() == "authorization" for k in headers):
            headers["Authorization"] = f"Bearer {create_token('owner')}"
        kwargs["headers"] = headers
        return original(self, method, url, **kwargs)

    monkeypatch.setattr(TestClient, "request", request)
