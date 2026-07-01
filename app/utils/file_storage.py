import shutil
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException, UploadFile, status

from ..config import settings


BASE_DIR = Path(__file__).resolve().parents[2]
MAX_UPLOAD_BYTES = 250 * 1024
ALLOWED_UPLOAD_EXTENSIONS = {".jpg", ".jpeg", ".png", ".pdf"}


def ensure_upload_directories() -> None:
    (BASE_DIR / settings.PHOTO_DIR).mkdir(parents=True, exist_ok=True)
    (BASE_DIR / settings.RECEIPT_DIR).mkdir(parents=True, exist_ok=True)
    (BASE_DIR / "uploads/error_reports").mkdir(parents=True, exist_ok=True)


def save_upload_file(upload_file: UploadFile, destination_dir: str, prefix: str) -> str:
    destination = BASE_DIR / destination_dir
    destination.mkdir(parents=True, exist_ok=True)

    extension = Path(upload_file.filename or "").suffix.lower()
    if extension not in ALLOWED_UPLOAD_EXTENSIONS:
      raise HTTPException(
          status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
          detail="Only JPG, JPEG, PNG, and PDF files are allowed.",
      )

    upload_file.file.seek(0, 2)
    file_size = upload_file.file.tell()
    upload_file.file.seek(0)
    if file_size > MAX_UPLOAD_BYTES:
      raise HTTPException(
          status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
          detail="Uploaded files must be 250 KB or smaller.",
      )

    safe_name = f"{prefix}_{uuid4().hex}{extension}"
    file_path = destination / safe_name

    with file_path.open("wb") as buffer:
        shutil.copyfileobj(upload_file.file, buffer)

    return str(file_path.relative_to(BASE_DIR)).replace("\\", "/")


def save_upload_file_bytes(file_buffer, destination_dir: str, filename: str) -> str:
    destination = BASE_DIR / destination_dir
    destination.mkdir(parents=True, exist_ok=True)
    file_path = destination / filename
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file_buffer, buffer)
    return str(file_path.relative_to(BASE_DIR)).replace("\\", "/")
