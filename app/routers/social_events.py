from html import unescape
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen
import re

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import SocialEvent
from ..schemas import SocialEventCreate, SocialEventResponse

router = APIRouter(tags=["social-events"])

DEFAULT_SOCIAL_TITLE = "Magadh Mahila College"
DEFAULT_SOCIAL_DESCRIPTION = "Official social media updates and events"
META_TAG_PATTERN = re.compile(r"<meta\b[^>]*>", re.IGNORECASE)
ATTRIBUTE_PATTERN = re.compile(r'([:@\w-]+)\s*=\s*([\'"])(.*?)\2', re.IGNORECASE | re.DOTALL)
WHITESPACE_PATTERN = re.compile(r"\s+")


def _clean_text(value: str | None) -> str:
    return (value or "").strip()


def _normalize_whitespace(value: str | None) -> str:
    return WHITESPACE_PATTERN.sub(" ", _clean_text(value))


def _extract_meta_tags(html: str) -> dict[str, str]:
    meta: dict[str, str] = {}
    for tag in META_TAG_PATTERN.findall(html):
        attributes = {
            key.lower(): unescape(value.strip())
            for key, _, value in ATTRIBUTE_PATTERN.findall(tag)
        }
        content = _normalize_whitespace(attributes.get("content"))
        if not content:
            continue

        for candidate in (attributes.get("property"), attributes.get("name")):
            normalized = _clean_text(candidate).lower()
            if normalized and normalized not in meta:
                meta[normalized] = content
    return meta


def _detect_platform_from_url(url: str) -> str:
    host = urlparse(url).netloc.lower()
    if "instagram.com" in host:
        return "Instagram"
    if "facebook.com" in host or "fb.watch" in host:
        return "Facebook"
    if "youtube.com" in host or "youtu.be" in host:
        return "YouTube"
    if "twitter.com" in host or "x.com" in host:
        return "Twitter"
    return "General"


def _fetch_social_preview(url: str) -> dict[str, str]:
    request = Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0 Safari/537.36"
            )
        },
    )

    try:
        with urlopen(request, timeout=8) as response:
            content_type = response.headers.get("Content-Type", "")
            if "text/html" not in content_type:
                return {}
            html = response.read().decode("utf-8", errors="ignore")
    except (URLError, ValueError, TimeoutError):
        return {}

    meta = _extract_meta_tags(html)
    return {
        "title": meta.get("og:title") or meta.get("twitter:title") or "",
        "description": meta.get("og:description") or meta.get("twitter:description") or meta.get("description") or "",
        "image_url": meta.get("og:image") or meta.get("twitter:image") or "",
    }


@router.get("/social-events", response_model=list[SocialEventResponse])
def list_social_events(
    limit: int = Query(default=12, ge=1, le=100),
    db: Session = Depends(get_db),
) -> list[SocialEvent]:
    stmt = (
        select(SocialEvent)
        .where(SocialEvent.is_active.is_(True))
        .order_by(desc(SocialEvent.created_at))
        .limit(limit)
    )
    return list(db.scalars(stmt))


@router.post("/social-events", response_model=SocialEventResponse, status_code=status.HTTP_201_CREATED)
def create_social_event(
    payload: SocialEventCreate,
    db: Session = Depends(get_db),
) -> SocialEvent:
    title = _clean_text(payload.title)
    description = _clean_text(payload.description)
    platform = _clean_text(payload.platform)
    social_url = _clean_text(payload.social_url)
    image_url = _clean_text(payload.image_url)
    if not social_url:
      raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="social_url is required.")

    preview = _fetch_social_preview(social_url)

    use_fetched_title = not title or title == DEFAULT_SOCIAL_TITLE
    use_fetched_description = not description or description == DEFAULT_SOCIAL_DESCRIPTION

    final_title = preview.get("title") or title or DEFAULT_SOCIAL_TITLE
    final_description = preview.get("description") if use_fetched_description else description
    final_image_url = image_url or preview.get("image_url") or None
    final_platform = platform or _detect_platform_from_url(social_url)

    event = SocialEvent(
        title=final_title if use_fetched_title else title,
        description=final_description or "",
        platform=final_platform or "General",
        social_url=social_url,
        image_url=final_image_url,
        is_active=True,
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event
