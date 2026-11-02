
import json
from pathlib import Path

from database import Base, SessionLocal, engine
from models import MenuItem
from migrate import upgrade_schema

# Project root is the parent directory of backend/.
BACKEND_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BACKEND_DIR.parent

MENU_FILE = PROJECT_DIR / "frontend" / "data" / "menu-demo.json"


def load_demo_menu():
    if not MENU_FILE.exists():
        raise FileNotFoundError(
            f"Menu file not found: {MENU_FILE}"
        )

    with MENU_FILE.open("r", encoding="utf-8") as file:
        menu_data = json.load(file)

    if not isinstance(menu_data, list):
        raise ValueError("The menu JSON must contain a list.")

    required_fields = {
        "id",
        "name",
        "price",
        "category",
        "dietary_tags",
        "ingredients",
        "description",
        "spice_level",
        "available",
        "image",
    }

    for item in menu_data:
        if not isinstance(item, dict):
            raise ValueError("Every menu record must be an object.")

        missing = required_fields - item.keys()

        if missing:
            raise ValueError(
                f"Menu item is missing fields: {sorted(missing)}"
            )

        if (
            not isinstance(item["id"], int)
            or isinstance(item["id"], bool)
            or not isinstance(item["price"], int)
            or isinstance(item["price"], bool)
            or item["price"] < 0
        ):
            raise ValueError(
                f"Invalid ID or price for menu item: {item['name']}"
            )

    return menu_data


def initialize_database(reset_menu: bool = False):
    # Create tables that do not already exist.
    added = upgrade_schema(engine)
    if added:
        print(f"Schema upgraded, columns added: {added}")

    menu_data = load_demo_menu()
    db = SessionLocal()

    try:
        inserted = 0
        updated = 0

        for item_data in menu_data:
            item = db.get(MenuItem, item_data["id"])

            if item is None:
                item = MenuItem(**item_data)
                db.add(item)
                inserted += 1
            elif reset_menu:
                # Only with --reset-menu: restore demo values (this discards owner edits).
                for field, value in item_data.items():
                    setattr(item, field, value)

                updated += 1

        db.commit()

        print("TasteFlow AI database initialized successfully.")
        print(f"Database file: {BACKEND_DIR / 'tasteflow.db'}")
        print(f"New dishes inserted: {inserted}")
        print(f"Existing dishes reset to demo values: {updated} (existing dishes are left untouched unless you pass --reset-menu)")
        print(f"Total dishes in source file: {len(menu_data)}")

    except Exception:
        db.rollback()
        raise

    finally:
        db.close()


if __name__ == "__main__":
    import sys

    initialize_database(reset_menu="--reset-menu" in sys.argv)
