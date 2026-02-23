from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .auth import ensure_default_admin
from .config import settings
from .database import Base, SessionLocal, engine
from .migrations import migrate_notices_publish_date
from .routers.auth import router as auth_router
from .routers.notices import router as notices_router
from .seed_notices import sync_notice_folder_to_db


def create_app() -> FastAPI:
    app = FastAPI(title=settings.app_name)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    upload_dir = Path(settings.upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/uploads", StaticFiles(directory=upload_dir), name="uploads")

    @app.on_event("startup")
    def startup_event() -> None:
        Base.metadata.create_all(bind=engine)
        migrate_notices_publish_date(engine)
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

    app.include_router(auth_router, prefix=settings.api_prefix)
    app.include_router(notices_router, prefix=settings.api_prefix)

    return app


app = create_app()
