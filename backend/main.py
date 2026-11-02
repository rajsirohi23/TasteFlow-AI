import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import config
from auth import router as auth_router
from database import engine
from migrate import upgrade_schema
from routers.agents import router as agents_router
from routers.chat import router as chat_router
from routers.command import router as command_router
from routers.kitchen import router as kitchen_router
from routers.menu import router as menu_router
from routers.menu_admin import router as menu_admin_router
from routers.orders import router as orders_router
from routers.owner import router as owner_router
from routers.track import router as track_router
from routers.voice import router as voice_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("tasteflow")


@asynccontextmanager
async def lifespan(app: FastAPI):
    added = upgrade_schema(engine)  # creates new tables, adds missing columns, never drops data
    if added:
        log.info("Schema upgraded, columns added: %s", added)
    if config.USING_DEMO_CREDENTIALS:
        log.warning("Using DEMO staff PINs. Set OWNER_PIN, KITCHEN_PIN and AUTH_SECRET in .env before any real use.")
    yield


app = FastAPI(
    title="TasteFlow AI API",
    description="Multi-agent restaurant operating system",
    version="0.2.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Content-Type", "Authorization"],
)


@app.get("/")
def home():
    return {"message": "Welcome to TasteFlow AI", "application": "TasteFlow Bistro", "status": "running"}


@app.get("/health")
def health_check():
    return {"status": "healthy", "service": "TasteFlow AI API"}


for r in (auth_router, menu_router, orders_router, kitchen_router, owner_router, menu_admin_router,
          agents_router, chat_router, track_router, command_router, voice_router):
    app.include_router(r)
