"""Guest-scoped property live slug issuance and lookup."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import secrets

from sqlalchemy.orm import Session

from app.models.guest_live_slug import GuestLiveSlug

GUEST_LIVE_SLUG_TTL_HOURS = 24.0  # hours — guest-scoped live link validity from slug creation


def _guest_slug_min_created_at(now: datetime, ttl_hours: float = GUEST_LIVE_SLUG_TTL_HOURS) -> datetime:
    return now - timedelta(hours=max(1 / 60, float(ttl_hours)))


def issue_guest_live_slug(
    db: Session,
    *,
    property_id: int,
    guest_user_id: int,
    unit_id: int | None,
    ttl_hours: float = GUEST_LIVE_SLUG_TTL_HOURS,
) -> str:
    """Return an active guest slug for property+unit; create one if missing/expired."""
    now = datetime.now(timezone.utc)
    min_created_at = _guest_slug_min_created_at(now, ttl_hours)
    q = (
        db.query(GuestLiveSlug)
        .filter(
            GuestLiveSlug.property_id == property_id,
            GuestLiveSlug.guest_user_id == guest_user_id,
            GuestLiveSlug.expires_at > now,
            GuestLiveSlug.created_at >= min_created_at,
        )
    )
    if unit_id is None:
        q = q.filter(GuestLiveSlug.unit_id.is_(None))
    else:
        q = q.filter(GuestLiveSlug.unit_id == unit_id)
    existing = q.order_by(GuestLiveSlug.expires_at.desc()).first()
    if existing and (existing.slug or "").strip():
        return existing.slug

    expires_at = now + timedelta(hours=max(1 / 60, float(ttl_hours)))
    for _ in range(15):
        slug = secrets.token_urlsafe(16).replace("+", "-").replace("/", "_")[:40]
        if db.query(GuestLiveSlug).filter(GuestLiveSlug.slug == slug).first() is None:
            row = GuestLiveSlug(
                property_id=property_id,
                guest_user_id=guest_user_id,
                unit_id=unit_id,
                slug=slug,
                expires_at=expires_at,
            )
            db.add(row)
            db.commit()
            return slug

    fallback = f"g-{guest_user_id}-{property_id}-{secrets.token_hex(8)}"
    row2 = GuestLiveSlug(
        property_id=property_id,
        guest_user_id=guest_user_id,
        unit_id=unit_id,
        slug=fallback,
        expires_at=expires_at,
    )
    db.add(row2)
    db.commit()
    return fallback


def resolve_guest_live_slug_row(db: Session, slug: str) -> GuestLiveSlug | None:
    """Resolve unexpired guest slug to full row."""
    s = (slug or "").strip()
    if not s:
        return None
    now = datetime.now(timezone.utc)
    min_created_at = _guest_slug_min_created_at(now)
    return (
        db.query(GuestLiveSlug)
        .filter(
            GuestLiveSlug.slug == s,
            GuestLiveSlug.expires_at > now,
            GuestLiveSlug.created_at >= min_created_at,
        )
        .order_by(GuestLiveSlug.expires_at.desc())
        .first()
    )
