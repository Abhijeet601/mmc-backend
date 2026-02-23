from datetime import datetime, timedelta, timezone

from jose import jwt
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .models import AdminUser

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def verify_password(plain_password: str, password_hash: str) -> bool:
    return pwd_context.verify(plain_password, password_hash)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def create_access_token(*, subject: str, expires_delta: timedelta | None = None) -> str:
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=settings.access_token_expire_minutes))
    payload = {"sub": subject, "exp": expire}
    return jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)


def authenticate_admin(db: Session, username: str, password: str) -> AdminUser | None:
    admin = db.scalar(select(AdminUser).where(AdminUser.username == username))
    if not admin:
        return None
    if not verify_password(password, admin.password_hash):
        return None
    return admin


def ensure_default_admin(db: Session) -> None:
    existing = db.scalar(select(AdminUser).where(AdminUser.username == settings.admin_username))
    if existing:
        return

    default_admin = AdminUser(
        username=settings.admin_username,
        password_hash=get_password_hash(settings.admin_password),
    )
    db.add(default_admin)
    db.commit()

