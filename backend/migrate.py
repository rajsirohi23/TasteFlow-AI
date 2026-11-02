"""Lightweight, safe schema upgrade for SQLite.

`Base.metadata.create_all` creates NEW tables but never adds columns to tables
that already exist. This helper adds any missing columns (it never drops or
rewrites data), so a database created by the first version keeps working.
For a larger production system we would move to Alembic migrations.
"""
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

from database import Base


def _sqlite_type(column) -> str:
    name = column.type.__class__.__name__.upper()
    return {"INTEGER": "INTEGER", "BOOLEAN": "BOOLEAN", "JSON": "JSON",
            "DATETIME": "DATETIME", "TEXT": "TEXT"}.get(name, "VARCHAR")


def upgrade_schema(engine: Engine) -> list[str]:
    import models  # noqa: F401  (registers all tables on Base)

    Base.metadata.create_all(bind=engine)
    inspector = inspect(engine)
    added: list[str] = []

    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            existing = {c["name"] for c in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in existing:
                    continue
                ddl = f'ALTER TABLE {table.name} ADD COLUMN {column.name} {_sqlite_type(column)}'
                default = column.default.arg if column.default is not None and not callable(column.default.arg) else None
                if default is not None and not column.nullable:
                    literal = int(default) if isinstance(default, bool) else (f"'{default}'" if isinstance(default, str) else default)
                    ddl += f" NOT NULL DEFAULT {literal}"
                conn.execute(text(ddl))
                added.append(f"{table.name}.{column.name}")
    return added
