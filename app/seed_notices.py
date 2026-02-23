from datetime import datetime, timezone
from pathlib import Path
import re
import shutil
from urllib.parse import quote

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Notice, NoticeCategory

ALLOWED_NOTICE_EXTENSIONS = {".pdf", ".doc", ".docx", ".jpg", ".jpeg", ".png"}
SEEDED_CATEGORIES = (NoticeCategory.NOTICES, NoticeCategory.NOTIFICATIONS)
BLOCKED_NOTICE_BASE_TITLES = {
    "anti ragging committee 2024",
    "nirf 2025",
    "notice for awantika hostel demolishing material auction",
}

DATE_PATTERNS = (
    r"\b\d{1,2}[./-]\d{1,2}[./-]\d{2,4}\b",  # 10.12.2025, 10-12-2025, 10/12/2025
    r"\b\d{4}[./-]\d{1,2}[./-]\d{1,2}\b",  # 2025-12-10
)


def filename_to_title(filename: str) -> str:
    stem = Path(filename).stem
    cleaned = stem.replace("-", " ").replace("_", " ")
    cleaned = re.sub(r"\bdated\b", " ", cleaned, flags=re.IGNORECASE)
    for pattern in DATE_PATTERNS:
        cleaned = re.sub(pattern, " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\(\s*\d+\s*\)$", "", cleaned).strip()  # strip suffix like "(1)"
    return " ".join(cleaned.split()).strip()


def normalize_for_match(value: str) -> str:
    cleaned = value.strip().lower()
    cleaned = cleaned.replace("-", " ").replace("_", " ")
    cleaned = re.sub(r"\(\s*\d+\s*\)$", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


def is_blocked_notice(*, file_name: str | None = None, title: str | None = None) -> bool:
    candidates: list[str] = []
    if file_name:
        candidates.append(normalize_for_match(Path(file_name).stem))
    if title:
        candidates.append(normalize_for_match(title))

    for candidate in candidates:
        for blocked in BLOCKED_NOTICE_BASE_TITLES:
            if candidate == blocked or candidate.startswith(f"{blocked} "):
                return True
    return False


def remove_blocked_notices(db: Session) -> int:
    deleted = 0
    notices = db.scalars(select(Notice)).all()
    for notice in notices:
        if is_blocked_notice(file_name=notice.file_name, title=notice.title):
            db.delete(notice)
            deleted += 1
    if deleted:
        db.commit()
    return deleted


def sync_notice_folder_to_db(
    db: Session,
    *,
    source_dir: Path,
    upload_root: Path,
) -> int:
    deleted_count = remove_blocked_notices(db)

    if not source_dir.exists() or not source_dir.is_dir():
        return deleted_count

    target_dir = upload_root / "source-notices"
    target_dir.mkdir(parents=True, exist_ok=True)

    existing_pairs = set(
        db.execute(
            select(Notice.file_name, Notice.publish_to).where(Notice.file_name.is_not(None))
        ).all()
    )

    created_count = 0
    updated_count = 0

    for file_path in sorted(source_dir.iterdir()):
        if not file_path.is_file():
            continue
        if file_path.suffix.lower() not in ALLOWED_NOTICE_EXTENSIONS:
            continue
        if is_blocked_notice(file_name=file_path.name):
            continue

        target_path = target_dir / file_path.name
        if (
            not target_path.exists()
            or target_path.stat().st_size != file_path.stat().st_size
            or int(target_path.stat().st_mtime) != int(file_path.stat().st_mtime)
        ):
            shutil.copy2(file_path, target_path)

        safe_name = quote(file_path.name)
        normalized_title = filename_to_title(file_path.name)
        normalized_file_url = f"/uploads/source-notices/{safe_name}"

        for category in SEEDED_CATEGORIES:
            key = (file_path.name, category)
            if key in existing_pairs:
                existing_notice = db.scalar(
                    select(Notice).where(
                        Notice.file_name == file_path.name,
                        Notice.publish_to == category,
                    )
                )
                if existing_notice is not None:
                    has_changes = False
                    if existing_notice.title != normalized_title:
                        existing_notice.title = normalized_title
                        has_changes = True
                    if existing_notice.file_url != normalized_file_url:
                        existing_notice.file_url = normalized_file_url
                        has_changes = True
                    if has_changes:
                        db.add(existing_notice)
                        updated_count += 1
                continue

            notice = Notice(
                title=normalized_title,
                description="",
                publish_to=category,
                link=None,
                file_url=normalized_file_url,
                file_name=file_path.name,
                published=True,
                pinned=False,
                publish_date=datetime.now(timezone.utc),
            )
            db.add(notice)
            existing_pairs.add(key)
            created_count += 1

    if created_count > 0 or updated_count > 0:
        db.commit()

    return created_count + updated_count + deleted_count
