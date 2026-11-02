"""Central configuration. Every setting comes from an environment variable
(or a local .env file) so no secret or URL is hard-coded in the code."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


def _load_dotenv() -> None:
    """Tiny .env reader (no extra dependency). Real env vars always win."""
    env_file = BASE_DIR / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv()

APP_ENV = os.getenv("APP_ENV", "dev")  # "dev" or "prod"

CORS_ORIGINS = [
    o.strip()
    for o in os.getenv(
        "CORS_ORIGINS",
        "http://localhost:5500,http://127.0.0.1:5500,"
        "http://localhost:5501,http://127.0.0.1:5501,"
        "http://localhost:8080,http://127.0.0.1:8080",
    ).split(",")
    if o.strip()
]

# --- Staff login (owner / kitchen) -------------------------------------
# In dev we allow demo PINs so the project runs out of the box, and we say so
# loudly. In prod the PINs and secret MUST come from the environment.
_DEV_DEFAULTS = {"OWNER_PIN": "owner-demo", "KITCHEN_PIN": "kitchen-demo",
                 "AUTH_SECRET": "dev-only-secret-change-me"}


def _secret(name: str) -> str:
    value = os.getenv(name)
    if value:
        return value
    if APP_ENV == "dev":
        return _DEV_DEFAULTS[name]
    raise RuntimeError(f"{name} must be set when APP_ENV=prod")


OWNER_PIN = _secret("OWNER_PIN")
KITCHEN_PIN = _secret("KITCHEN_PIN")
AUTH_SECRET = _secret("AUTH_SECRET")
USING_DEMO_CREDENTIALS = APP_ENV == "dev" and not os.getenv("OWNER_PIN")
TOKEN_TTL_SECONDS = int(os.getenv("TOKEN_TTL_SECONDS", str(8 * 3600)))

# --- Kitchen model ------------------------------------------------------
# Preparation minutes are NOT measured data. They are editable estimates used
# only when a dish has no prep_minutes value of its own.
CATEGORY_PREP_MINUTES = {
    "Starters": 8, "Main Course": 15, "Bowls": 10, "Salads": 6,
    "Drinks": 3, "Desserts": 5, "Breakfast": 10,
}
DEFAULT_PREP_MINUTES = 10
KITCHEN_PARALLEL_STATIONS = int(os.getenv("KITCHEN_PARALLEL_STATIONS", "3"))
KITCHEN_BUSY_WAIT_MINUTES = int(os.getenv("KITCHEN_BUSY_WAIT_MINUTES", "25"))
KITCHEN_MODERATE_WAIT_MINUTES = int(os.getenv("KITCHEN_MODERATE_WAIT_MINUTES", "12"))

# Analytics honesty: below this many orders we say "not enough data".
MIN_ORDERS_FOR_INSIGHTS = int(os.getenv("MIN_ORDERS_FOR_INSIGHTS", "30"))

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Safety limit: one order cannot contain more than this many items in total.
MAX_ITEMS_PER_ORDER = int(os.getenv("MAX_ITEMS_PER_ORDER", "30"))

# The restaurant's local time (India = UTC+5:30). Orders are stored in UTC;
# "today" and "peak hour" analytics are converted with this offset.
RESTAURANT_UTC_OFFSET_MINUTES = int(os.getenv("RESTAURANT_UTC_OFFSET_MINUTES", "330"))

# Order tracking and stock.
DEFAULT_ETA_MINUTES = int(os.getenv("DEFAULT_ETA_MINUTES", "15"))   # for orders placed before tracking existed
MIN_ETA_MINUTES = int(os.getenv("MIN_ETA_MINUTES", "5"))
LOW_STOCK_THRESHOLD = int(os.getenv("LOW_STOCK_THRESHOLD", "5"))

# An order still "active" after this many hours is treated as abandoned: it no longer
# inflates wait-time estimates, and the kitchen board flags it so staff can clear it.
STALE_ORDER_HOURS = int(os.getenv("STALE_ORDER_HOURS", "6"))

# Command Center
TABLE_COUNT = int(os.getenv("TABLE_COUNT", "12"))
SLA_MINUTES = int(os.getenv("SLA_MINUTES", "20"))   # target: order ready within this many minutes
