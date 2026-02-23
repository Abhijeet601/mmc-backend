import enum
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class NoticeCategory(str, enum.Enum):
    TENDERS = "tenders"
    UPCOMING_EVENTS = "upcoming_events"
    NOTIFICATIONS = "notifications"
    NOTICES = "notices"


class AdminUser(Base):
    __tablename__ = "admin_users"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    username: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    notices: Mapped[list["Notice"]] = relationship(back_populates="created_by_admin")


class Notice(Base):
    __tablename__ = "notices"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    publish_to: Mapped[NoticeCategory] = mapped_column(Enum(NoticeCategory), nullable=False, index=True)

    link: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    file_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    file_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    published: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    pinned: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    publish_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=True,
        index=True,
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False, index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )

    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("admin_users.id"), nullable=True)
    created_by_admin: Mapped[AdminUser | None] = relationship(back_populates="notices")
