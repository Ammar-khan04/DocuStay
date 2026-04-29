"""Tenant-scoped property live slug issuance and lookup."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import secrets

from sqlalchemy.orm import Session

from app.models.tenant_live_slug import TenantLiveSlug

TENANT_LIVE_SLUG_TTL_HOURS = 24.0  # hours — tenant-scoped live link validity from slug creation


def _tenant_slug_min_created_at(now: datetime, ttl_hours: float = TENANT_LIVE_SLUG_TTL_HOURS) -> datetime:
    return now - timedelta(hours=max(1 / 60, float(ttl_hours)))


def issue_tenant_live_slug(
    db: Session,
    *,
    property_id: int,
    tenant_user_id: int,
    ttl_hours: float = TENANT_LIVE_SLUG_TTL_HOURS,
) -> str:
    """Return an active tenant slug for property; create one if missing/expired."""
    now = datetime.now(timezone.utc)
    min_created_at = _tenant_slug_min_created_at(now, ttl_hours)
    existing = (
        db.query(TenantLiveSlug)
        .filter(
            TenantLiveSlug.property_id == property_id,
            TenantLiveSlug.tenant_user_id == tenant_user_id,
            TenantLiveSlug.expires_at > now,
            TenantLiveSlug.created_at >= min_created_at,
        )
        .order_by(TenantLiveSlug.expires_at.desc())
        .first()
    )
    if existing and (existing.slug or "").strip():
        return existing.slug

    expires_at = now + timedelta(hours=max(1 / 60, float(ttl_hours)))
    for _ in range(15):
        slug = secrets.token_urlsafe(16).replace("+", "-").replace("/", "_")[:40]
        if db.query(TenantLiveSlug).filter(TenantLiveSlug.slug == slug).first() is None:
            row = TenantLiveSlug(
                property_id=property_id,
                tenant_user_id=tenant_user_id,
                slug=slug,
                expires_at=expires_at,
            )
            db.add(row)
            # Persist immediately so the returned slug is resolvable on the next request.
            db.commit()
            return slug

    fallback = f"t-{tenant_user_id}-{property_id}-{secrets.token_hex(8)}"
    row2 = TenantLiveSlug(
        property_id=property_id,
        tenant_user_id=tenant_user_id,
        slug=fallback,
        expires_at=expires_at,
    )
    db.add(row2)
    # Persist immediately so the returned slug is resolvable on the next request.
    db.commit()
    return fallback


def resolve_tenant_live_slug_property_id(db: Session, slug: str) -> int | None:
    """Resolve unexpired tenant slug to property_id."""
    s = (slug or "").strip()
    if not s:
        return None
    now = datetime.now(timezone.utc)
    min_created_at = _tenant_slug_min_created_at(now)
    row = (
        db.query(TenantLiveSlug)
        .filter(
            TenantLiveSlug.slug == s,
            TenantLiveSlug.expires_at > now,
            TenantLiveSlug.created_at >= min_created_at,
        )
        .order_by(TenantLiveSlug.expires_at.desc())
        .first()
    )
    return row.property_id if row else None


def resolve_tenant_live_slug_row(db: Session, slug: str) -> TenantLiveSlug | None:
    """Resolve unexpired tenant slug to full row."""
    s = (slug or "").strip()
    if not s:
        return None
    now = datetime.now(timezone.utc)
    min_created_at = _tenant_slug_min_created_at(now)
    return (
        db.query(TenantLiveSlug)
        .filter(
            TenantLiveSlug.slug == s,
            TenantLiveSlug.expires_at > now,
            TenantLiveSlug.created_at >= min_created_at,
        )
        .order_by(TenantLiveSlug.expires_at.desc())
        .first()
    )
