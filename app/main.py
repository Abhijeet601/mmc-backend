import logging
import time
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from . import erp_models  # noqa: F401
from .api.router import api_router
from .auth import ensure_default_admin
from .config import settings
from .database import Base, SessionLocal, database_url, engine, test_connection
from .middleware.rate_limit import RateLimitMiddleware
from .migrations import (
    migrate_admin_users_username,
    migrate_notices_is_active,
    migrate_notices_publish_date,
    migrate_notices_publish_to_values,
    migrate_plaintext_passwords,
)
from .models import AdminUser, Notice, SocialEvent  # noqa: F401
from .models.erp import ERPHostelRoom
from .routers.notices import router as notices_router
from .routers.social_events import router as social_events_router
from .seed_notices import sync_notice_folder_to_db
from .utils.file_storage import ensure_upload_directories

DEFAULT_HOSTEL_ROOMS = [
    ("Vaidehi Hostel", "A", "101", 3),
    ("Vaidehi Hostel", "A", "102", 3),
    ("Vaidehi Hostel", "A", "103", 3),
    ("Vaidehi Hostel", "B", "201", 3),
    ("Vaidehi Hostel", "B", "202", 3),
    ("Vaidehi Hostel", "B", "203", 3),
    ("Mahima Hostel", "A", "101", 2),
    ("Mahima Hostel", "A", "102", 2),
    ("Mahima Hostel", "A", "103", 2),
    ("Mahima Hostel", "B", "201", 2),
    ("Mahima Hostel", "B", "202", 2),
    ("Mahima Hostel", "B", "203", 2),
]

logger = logging.getLogger(__name__)

_WAIT_RETRIES = 60
_WAIT_INTERVAL = 2  # seconds


def wait_for_db() -> None:
    """Block until the database accepts a connection or retries are exhausted.

    Key behaviours:
    - Catches *all* exceptions (not just OperationalError) so transient
      network errors, refused connections, and timeouts are all handled.
    - Disposes the engine connection pool between attempts so SQLAlchemy
      never reuses a cached failed connection.
    - Logs the sanitised database URL on the first attempt so the target
      host/port is visible in the deployment logs.
    - Raises RuntimeError after all retries are exhausted so the process
      exits with a non-zero code and Railway restarts it.
    """
    if not database_url:
        raise RuntimeError(
            "DATABASE_URL is not set. Cannot start the application without a database connection."
        )

    try:
        from sqlalchemy.engine.url import make_url as _make_url
        _safe_url = _make_url(database_url).render_as_string(hide_password=True)
    except Exception:
        _safe_url = "<unparseable URL>"

    logger.info(
        "Waiting for database to become available (up to %d attempts, %ds apart). URL: %s",
        _WAIT_RETRIES,
        _WAIT_INTERVAL,
        _safe_url,
    )

    last_exc: Exception | None = None
    for attempt in range(1, _WAIT_RETRIES + 1):
        try:
            test_connection()
            logger.info("Database is ready (attempt %d/%d).", attempt, _WAIT_RETRIES)
            return
        except Exception as exc:  # noqa: BLE001 — intentionally broad
            last_exc = exc
            logger.warning(
                "Database not ready yet (attempt %d/%d): %s: %s",
                attempt,
                _WAIT_RETRIES,
                type(exc).__name__,
                exc,
            )
            # Dispose the pool so the next attempt opens a brand-new connection
            # rather than reusing a cached, broken one.
            try:
                engine.dispose()
            except Exception:  # noqa: BLE001
                pass
            if attempt < _WAIT_RETRIES:
                time.sleep(_WAIT_INTERVAL)

    raise RuntimeError(
        f"Database did not become available after {_WAIT_RETRIES} attempts "
        f"({_WAIT_RETRIES * _WAIT_INTERVAL}s). Last error: {last_exc}"
    )


def seed_default_hostel_rooms() -> None:
    with SessionLocal() as db:
        existing = db.query(ERPHostelRoom).first()
        if existing:
            return
        for hostel_name, block_name, room_number, bed_capacity in DEFAULT_HOSTEL_ROOMS:
            db.add(
                ERPHostelRoom(
                    hostel_name=hostel_name,
                    block_name=block_name,
                    room_number=room_number,
                    bed_capacity=bed_capacity,
                    is_active=True,
                )
            )
        db.commit()


def create_app() -> FastAPI:
    app = FastAPI(
        title="Magadh Mahila College Hostel ERP",
        version="2.0.0",
        description="Production-oriented hostel admission, allocation, payment, receipt, complaint, and reporting APIs.",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_origin_regex=settings.cors_allow_origin_regex,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(RateLimitMiddleware, limit=180, window_seconds=60)

    upload_dir = Path(settings.upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/uploads", StaticFiles(directory=upload_dir), name="uploads")

    @app.on_event("startup")
    def startup_event() -> None:
        wait_for_db()
        ensure_upload_directories()
        Base.metadata.create_all(bind=engine)
        migrate_admin_users_username(engine)
        migrate_notices_publish_date(engine)
        migrate_notices_is_active(engine)
        migrate_notices_publish_to_values(engine)
        seed_default_hostel_rooms()
        
        logger.info("Running password migration check on startup...")
        migration_result = migrate_plaintext_passwords(engine, SessionLocal)
        
        if migration_result["needs_migration"]:
            for item in migration_result["needs_migration"]:
                logger.warning(
                    f"SECURITY: Plain text password detected for admin '{item['username']}'. "
                    f"Please run password migration manually. "
                    f"To migrate, use: force_migrate_plaintext_password(engine, SessionLocal, '{item['username']}', '<plain_password>')"
                )
        
        if migration_result["errors"]:
            for item in migration_result["errors"]:
                logger.error(f"Password hash error for admin '{item.get('username', 'unknown')}': {item.get('issue', 'Unknown error')}")
        
        logger.info(f"Password check complete. Checked: {migration_result['checked']}, Needs migration: {len(migration_result['needs_migration'])}")
        
        with SessionLocal() as db:
            ensure_default_admin(db)
            sync_notice_folder_to_db(
                db,
                source_dir=Path(settings.notice_source_dir),
                upload_root=Path(settings.upload_dir),
            )

    @app.get(f"{settings.api_prefix}/health")
    def health_check() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(api_router)
    app.include_router(notices_router, prefix=settings.api_prefix)
    app.include_router(social_events_router)
    app.include_router(social_events_router, prefix=settings.api_prefix)

    return app


app = create_app()
