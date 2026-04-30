"""Owner-scoped property live slug issuance and lookup."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import secrets

from sqlalchemy.orm import Session

from app.models.owner_live_slug import OwnerLiveSlug

OWNER_LIVE_SLUG_TTL_HOURS = 24.0  # hours — owner-scoped live link validity from slug creation


def _owner_slug_min_created_at(now: datetime, ttl_hours: float = OWNER_LIVE_SLUG_TTL_HOURS) -> datetime:
    return now - timedelta(hours=max(1 / 60, float(ttl_hours)))


def issue_owner_live_slug(
    db: Session,
    *,
    property_id: int,
    owner_user_id: int,
    ttl_hours: float = OWNER_LIVE_SLUG_TTL_HOURS,
) -> str:
    """Return an active owner slug for property; create one if missing/expired."""
    now = datetime.now(timezone.utc)
    min_created_at = _owner_slug_min_created_at(now, ttl_hours)
    existing = (
        db.query(OwnerLiveSlug)
        .filter(
            OwnerLiveSlug.property_id == property_id,
            OwnerLiveSlug.owner_user_id == owner_user_id,
            OwnerLiveSlug.expires_at > now,
            OwnerLiveSlug.created_at >= min_created_at,
        )
        .order_by(OwnerLiveSlug.expires_at.desc())
        .first()
    )
    if existing and (existing.slug or "").strip():
        return existing.slug

    expires_at = now + timedelta(hours=max(1 / 60, float(ttl_hours)))
    for _ in range(15):
        slug = secrets.token_urlsafe(16).replace("+", "-").replace("/", "_")[:40]
        if db.query(OwnerLiveSlug).filter(OwnerLiveSlug.slug == slug).first() is None:
            row = OwnerLiveSlug(
                property_id=property_id,
                owner_user_id=owner_user_id,
                slug=slug,
                expires_at=expires_at,
            )
            db.add(row)
            db.commit()
            return slug

    fallback = f"o-{owner_user_id}-{property_id}-{secrets.token_hex(8)}"
    row2 = OwnerLiveSlug(
        property_id=property_id,
        owner_user_id=owner_user_id,
        slug=fallback,
        expires_at=expires_at,
    )
    db.add(row2)
    db.commit()
    return fallback


def resolve_owner_live_slug_row(db: Session, slug: str) -> OwnerLiveSlug | None:
    """Resolve unexpired owner slug to full row."""
    s = (slug or "").strip()
    if not s:
        return None
    now = datetime.now(timezone.utc)
    min_created_at = _owner_slug_min_created_at(now)
    return (
        db.query(OwnerLiveSlug)
        .filter(
            OwnerLiveSlug.slug == s,
            OwnerLiveSlug.expires_at > now,
            OwnerLiveSlug.created_at >= min_created_at,
        )
        .order_by(OwnerLiveSlug.expires_at.desc())
        .first()
    )

