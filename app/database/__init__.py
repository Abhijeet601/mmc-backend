import os
import re

from sqlalchemy import create_engine
from sqlalchemy.engine import URL
from sqlalchemy.engine.url import make_url
from sqlalchemy.exc import ArgumentError
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from ..config import settings

REFERENCE_PATTERN = re.compile(r"\$\{\{([^}]+)\}\}|\$\{([^}]+)\}|\{\{([^}]+)\}\}")


def _is_unresolved_env_reference(value: str) -> bool:
    return bool(REFERENCE_PATTERN.search(value))


def _strip_wrapping_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1].strip()
    return value


def _lookup_placeholder_value(token: str) -> str:
    normalized = token.strip()
    candidates = [
        normalized,
        normalized.upper(),
        normalized.replace(".", "_"),
        normalized.replace(".", "_").upper(),
    ]
    if "." in normalized:
        tail = normalized.split(".")[-1]
        candidates.extend([tail, tail.upper(), tail.replace(".", "_"), tail.replace(".", "_").upper()])

    for key in dict.fromkeys(filter(None, candidates)):
        env_val = os.getenv(key)
        if env_val:
            return _strip_wrapping_quotes(env_val.strip())
    return ""


def _expand_env_references(value: str) -> str:
    def replacer(match: re.Match[str]) -> str:
        token = next((group for group in match.groups() if group), "")
        replacement = _lookup_placeholder_value(token)
        return replacement or match.group(0)

    return REFERENCE_PATTERN.sub(replacer, value)


def _clean_env_value(value: str | None) -> str:
    if value is None:
        return ""
    return _strip_wrapping_quotes(_expand_env_references(value.strip()).strip())


def _first_env_value(*keys: str) -> str:
    for key in keys:
        value = _clean_env_value(os.getenv(key))
        if value:
            return value
    return ""


def normalize_database_url(url: str) -> str:
    normalized = _strip_wrapping_quotes(url.strip())
    if normalized.startswith("mysql2://"):
        return normalized.replace("mysql2://", "mysql+pymysql://", 1)
    if normalized.startswith("mysql://"):
        return normalized.replace("mysql://", "mysql+pymysql://", 1)
    return normalized


def _build_mysql_url_from_parts() -> str | None:
    host = _first_env_value("MYSQLHOST", "MYSQL_HOST")
    port = _first_env_value("MYSQLPORT", "MYSQL_PORT")
    user = _first_env_value("MYSQLUSER", "MYSQL_USER")
    password = _first_env_value("MYSQLPASSWORD", "MYSQL_PASSWORD", "MYSQL_ROOT_PASSWORD")
    database = _first_env_value("MYSQLDATABASE", "MYSQL_DATABASE")
    if not all([host, port, user, password, database]) or any(_is_unresolved_env_reference(item) for item in [host, port, user, password, database]):
        return None
    try:
        port_number = int(port)
    except ValueError:
        return None
    return URL.create(
        drivername="mysql+pymysql",
        username=user,
        password=password,
        host=host,
        port=port_number,
        database=database,
    ).render_as_string(hide_password=False)


def _resolve_database_url() -> str:
    candidates = [
        _clean_env_value(os.getenv("DATABASE_URL")),
        _clean_env_value(os.getenv("MYSQL_URL")),
        _clean_env_value(os.getenv("MYSQL_PUBLIC_URL")),
    ]
    for candidate in candidates:
        normalized = normalize_database_url(candidate)
        if not normalized or _is_unresolved_env_reference(normalized):
            continue
        try:
            make_url(normalized)
            return normalized
        except ArgumentError:
            continue

    mysql_url = _build_mysql_url_from_parts()
    if mysql_url:
        return mysql_url

    return normalize_database_url(settings.database_url)


database_url = _resolve_database_url()
connect_args: dict[str, bool] = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
engine = create_engine(database_url, connect_args=connect_args, pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
