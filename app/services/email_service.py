from __future__ import annotations

from ..config import settings


def send_receipt_email(
    *,
    recipient: str | None,
    student_name: str,
    subject: str,
    body: str,
    receipt_path: str | None = None,
) -> str:
    if not recipient:
        return "skipped"
    # SMTP wiring can be added via environment configuration. Until then, the
    # backend records the workflow without blocking receipt generation.
    return "queued"


def send_account_email(*, recipient: str | None, subject: str, body: str) -> str:
    if not recipient:
        return "skipped"
    if not settings.SMTP_HOST or not settings.SMTP_FROM_EMAIL:
        return "skipped"
    return "queued"
