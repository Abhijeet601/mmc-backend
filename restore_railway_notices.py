"""One-off, idempotent restore of notice rows from mmc.db to Railway MySQL."""

import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path

from sqlalchemy import create_engine, inspect, select

from app.database import Base
from app.models import AdminUser, Notice  # noqa: F401 - registers metadata


ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "mmc.db"
BACKUP_DIR = ROOT / "railway_backups"


def mysql_url() -> str:
    value = os.getenv("MYSQL_PUBLIC_URL") or os.getenv("DATABASE_URL")
    if not value:
        raise RuntimeError("MYSQL_PUBLIC_URL or DATABASE_URL is required")
    return value.replace("mysql://", "mysql+pymysql://", 1)


def json_default(value):
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


with sqlite3.connect(SOURCE) as source:
    source.row_factory = sqlite3.Row
    source_rows = [dict(row) for row in source.execute("SELECT * FROM notices ORDER BY id")]

if not source_rows:
    raise RuntimeError("Source contains no notices; refusing to modify Railway")

engine = create_engine(mysql_url(), pool_pre_ping=True)
notice_table = Base.metadata.tables["notices"]
admin_table = Base.metadata.tables["admin_users"]

with engine.begin() as connection:
    existing_tables = set(inspect(connection).get_table_names())
    existing_rows = []
    if "notices" in existing_tables:
        existing_rows = [dict(row._mapping) for row in connection.execute(select(notice_table))]

    BACKUP_DIR.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = BACKUP_DIR / f"railway-notices-before-restore-{stamp}.json"
    backup.write_text(json.dumps(existing_rows, indent=2, default=json_default), encoding="utf-8")

    admin_table.create(connection, checkfirst=True)
    notice_table.create(connection, checkfirst=True)

    if existing_rows:
        raise RuntimeError(
            f"Railway already contains {len(existing_rows)} notices; backup saved to {backup}. "
            "Refusing to overwrite them."
        )

    target_columns = set(notice_table.c.keys())
    payload = [{key: value for key, value in row.items() if key in target_columns} for row in source_rows]
    connection.execute(notice_table.insert(), payload)

with engine.connect() as connection:
    restored = connection.execute(select(notice_table.c.id).order_by(notice_table.c.id)).scalars().all()

expected = [row["id"] for row in source_rows]
if restored != expected:
    raise RuntimeError(f"Verification failed: expected IDs {expected}, got {restored}")

print(f"Restored and verified {len(restored)} notices")
print(f"IDs: {','.join(map(str, restored))}")
print(f"Pre-restore backup: {backup}")
