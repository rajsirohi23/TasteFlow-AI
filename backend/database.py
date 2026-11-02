
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

# Store the database inside the backend directory.
BASE_DIR = Path(__file__).resolve().parent
DATABASE_URL = f"sqlite:///{BASE_DIR / 'tasteflow.db'}"

# SQLite needs this option for normal FastAPI multi-threaded use.
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
)

# Each session is used for a unit of database work.
SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
)

# All SQLAlchemy models inherit from this base.
Base = declarative_base()



def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()