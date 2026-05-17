from __future__ import annotations


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
