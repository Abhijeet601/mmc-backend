from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import settings

# ✅ Read DB URL
database_url = settings.database_url

# 🔥 FIX for Railway MySQL
if database_url and database_url.startswith("mysql://"):
    database_url = database_url.replace(
        "mysql://",
        "mysql+pymysql://",
        1,
    )

# ✅ SQLite special handling
connect_args: dict[str, bool] = {}
if database_url.startswith("sqlite"):
    connect_args = {"check_same_thread": False}

# ✅ Create engine
engine = create_engine(
    database_url,
    connect_args=connect_args,
    pool_pre_ping=True,
    future=True,
)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    future=True,
)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()