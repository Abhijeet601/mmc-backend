import os

from sqlalchemy import create_engine
from sqlalchemy.exc import ArgumentError
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.engine.url import make_url

from .config import settings


def _is_unresolved_railway_reference(value: str) -> bool:
    return value.startswith("${{") and value.endswith("}}")


def _strip_wrapping_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1].strip()
    return value


def _resolve_raw_database_url() -> str:
    env_database_url = (os.getenv("DATABASE_URL") or "").strip()
    env_mysql_url = (os.getenv("MYSQL_URL") or "").strip()

    if env_database_url and not _is_unresolved_railway_reference(env_database_url):
        return env_database_url

    if env_mysql_url:
        return env_mysql_url

    if env_database_url:
        return env_database_url

    return settings.database_url


def normalize_database_url(url: str) -> str:
    """Convert Railway-style MySQL URLs into SQLAlchemy PyMySQL URLs."""
    normalized = _strip_wrapping_quotes(url.strip())

    if normalized.startswith("mysql2://"):
        normalized = normalized.replace("mysql2://", "mysql+pymysql://", 1)

    if normalized.startswith("mysql://"):
        normalized = normalized.replace("mysql://", "mysql+pymysql://", 1)

    return normalized


def validate_database_url(url: str) -> str:
    try:
        make_url(url)
    except ArgumentError as exc:
        raise RuntimeError(
            "Invalid database URL. Configure Railway with MYSQL_URL, or set "
            "DATABASE_URL to a valid SQLAlchemy URL (for MySQL use mysql:// or mysql+pymysql://)."
        ) from exc

    return url


database_url = validate_database_url(normalize_database_url(_resolve_raw_database_url()))

connect_args: dict[str, bool] = {}
if database_url.startswith("sqlite"):
    connect_args = {"check_same_thread": False}

engine = create_engine(database_url, connect_args=connect_args, pool_pre_ping=True, future=True)

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
