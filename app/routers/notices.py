from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4
import shutil

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy import desc, or_, select
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..dependencies import get_current_admin
from ..models import AdminUser, Notice, NoticeCategory
from ..schemas import CategoryItem, NoticeResponse

router = APIRouter(prefix="/notices", tags=["notices"])

CATEGORY_LABELS: dict[NoticeCategory, str] = {
    NoticeCategory.TENDERS: "Tenders",
    NoticeCategory.UPCOMING_EVENTS: "Upcoming Events",
    NoticeCategory.NOTIFICATIONS: "Notifications",
    NoticeCategory.NOTICES: "Notices",
}


def parse_optional_datetime(value: str | None, field_name: str) -> datetime | None:
    if value is None:
        return None

    cleaned = value.strip()
    if not cleaned:
        return None

    if cleaned.endswith("Z"):
        cleaned = cleaned[:-1] + "+00:00"

    try:
        parsed = datetime.fromisoformat(cleaned)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid {field_name}. Use ISO-8601 date-time format.",
        ) from exc

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)

    return parsed.astimezone(timezone.utc)


def normalize_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def file_name_from_url(file_url: str | None) -> str | None:
    if not file_url:
        return None
    parsed = urlparse(file_url)
    path = parsed.path or file_url
    name = Path(path).name
    return name or None


def get_upload_root() -> Path:
    root = Path(settings.upload_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


async def save_upload_file(file: UploadFile) -> tuple[str, str]:
    upload_root = get_upload_root()
    target_dir = upload_root / "notices"
    target_dir.mkdir(parents=True, exist_ok=True)

    original_name = (file.filename or "upload").strip() or "upload"
    suffix = Path(original_name).suffix
    generated_name = f"{uuid4().hex}{suffix}"
    target_path = target_dir / generated_name

    with target_path.open("wb") as out_file:
        shutil.copyfileobj(file.file, out_file)

    await file.close()
    return f"/uploads/notices/{generated_name}", original_name


def delete_uploaded_file(file_url: str | None) -> None:
    if not file_url or not file_url.startswith("/uploads/"):
        return

    upload_root = get_upload_root()
    relative_path = file_url[len("/uploads/") :]
    candidate = (upload_root / relative_path).resolve()
    if upload_root not in candidate.parents:
        return

    if candidate.exists() and candidate.is_file():
        candidate.unlink()


def get_notice_or_404(db: Session, notice_id: int) -> Notice:
    notice = db.get(Notice, notice_id)
    if not notice:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notice not found.")
    return notice


@router.get("/categories", response_model=list[CategoryItem])
def list_categories() -> list[CategoryItem]:
    return [CategoryItem(value=key, label=value) for key, value in CATEGORY_LABELS.items()]


@router.get("", response_model=list[NoticeResponse])
def list_public_notices(
    publish_to: NoticeCategory | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> list[Notice]:
    now = datetime.now(timezone.utc)
    stmt = select(Notice).where(Notice.is_active.is_(True)).where(
        or_(Notice.publish_date.is_(None), Notice.publish_date <= now)
    )

    if publish_to:
        stmt = stmt.where(Notice.publish_to == publish_to)

    stmt = stmt.order_by(desc(Notice.pinned), desc(Notice.publish_date), desc(Notice.created_at)).limit(limit)
    return list(db.scalars(stmt))


@router.get("/admin", response_model=list[NoticeResponse])
def list_admin_notices(
    publish_to: NoticeCategory | None = Query(default=None),
    db: Session = Depends(get_db),
    _: AdminUser = Depends(get_current_admin),
) -> list[Notice]:
    stmt = select(Notice)
    if publish_to:
        stmt = stmt.where(Notice.publish_to == publish_to)

    stmt = stmt.order_by(desc(Notice.pinned), desc(Notice.publish_date), desc(Notice.created_at))
    return list(db.scalars(stmt))


@router.get("/admin/{notice_id}", response_model=NoticeResponse)
def get_admin_notice(
    notice_id: int,
    db: Session = Depends(get_db),
    _: AdminUser = Depends(get_current_admin),
) -> Notice:
    return get_notice_or_404(db, notice_id)


@router.post("/admin", response_model=NoticeResponse, status_code=status.HTTP_201_CREATED)
async def create_notice(
    title: str = Form(...),
    description: str = Form(default=""),
    publish_to: NoticeCategory = Form(...),
    link: str | None = Form(default=None),
    file_url: str | None = Form(default=None),
    pinned: bool = Form(default=False),
    published: bool = Form(default=True),
    publish_date: str | None = Form(default=None),
    file: UploadFile | None = File(default=None),
    db: Session = Depends(get_db),
    current_admin: AdminUser = Depends(get_current_admin),
) -> Notice:
    cleaned_title = title.strip()
    if not cleaned_title:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Title is required.",
        )

    stored_file_url = normalize_optional_text(file_url)
    stored_file_name = file_name_from_url(stored_file_url)

    if file is not None:
        stored_file_url, stored_file_name = await save_upload_file(file)

    notice = Notice(
        title=cleaned_title,
        description=description.strip(),
        publish_to=publish_to,
        link=normalize_optional_text(link),
        file_url=stored_file_url,
        file_name=stored_file_name,
        pinned=pinned,
        is_active=published,
        publish_date=parse_optional_datetime(publish_date, "publish_date") or datetime.now(timezone.utc),
        created_by_id=current_admin.id,
    )
    db.add(notice)
    db.commit()
    db.refresh(notice)
    return notice


@router.patch("/admin/{notice_id}", response_model=NoticeResponse)
async def update_notice(
    notice_id: int,
    title: str | None = Form(default=None),
    description: str | None = Form(default=None),
    publish_to: NoticeCategory | None = Form(default=None),
    link: str | None = Form(default=None),
    file_url: str | None = Form(default=None),
    pinned: bool | None = Form(default=None),
    published: bool | None = Form(default=None),
    publish_date: str | None = Form(default=None),
    remove_file: bool = Form(default=False),
    file: UploadFile | None = File(default=None),
    db: Session = Depends(get_db),
    _: AdminUser = Depends(get_current_admin),
) -> Notice:
    notice = get_notice_or_404(db, notice_id)

    if title is not None:
        cleaned_title = title.strip()
        if not cleaned_title:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Title is required.",
            )
        notice.title = cleaned_title

    if description is not None:
        notice.description = description.strip()
    if publish_to is not None:
        notice.publish_to = publish_to
    if link is not None:
        notice.link = normalize_optional_text(link)
    if pinned is not None:
        notice.pinned = pinned
    if published is not None:
        notice.is_active = published
    if publish_date is not None:
        parsed_publish_date = parse_optional_datetime(publish_date, "publish_date")
        notice.publish_date = parsed_publish_date or datetime.now(timezone.utc)

    if file is not None:
        delete_uploaded_file(notice.file_url)
        notice.file_url, notice.file_name = await save_upload_file(file)
    elif remove_file:
        delete_uploaded_file(notice.file_url)
        notice.file_url = None
        notice.file_name = None
    elif file_url is not None:
        normalized_url = normalize_optional_text(file_url)
        if normalized_url != notice.file_url:
            delete_uploaded_file(notice.file_url)
        notice.file_url = normalized_url
        notice.file_name = file_name_from_url(normalized_url)

    db.add(notice)
    db.commit()
    db.refresh(notice)
    return notice


@router.delete("/admin/{notice_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_notice(
    notice_id: int,
    db: Session = Depends(get_db),
    _: AdminUser = Depends(get_current_admin),
) -> None:
    notice = get_notice_or_404(db, notice_id)
    delete_uploaded_file(notice.file_url)
    db.delete(notice)
    db.commit()
    return None
