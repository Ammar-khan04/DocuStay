"""Append-only audit log service. Never update or delete - immutable audit trail."""
from __future__ import annotations

import enum
from datetime import date, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog
from app.models.invitation import Invitation
from app.models.stay import Stay
from app.models.user import User, UserRole
from app.services.privacy_lanes import is_tenant_lane_invitation, is_tenant_lane_stay

# Stored on each row in ``meta`` (JSONB) for filtering and display.
META_ACTING_ROLE = "acting_role"
META_LANE_CONTEXT = "lane_context"

CATEGORY_STATUS_CHANGE = "status_change"
CATEGORY_GUEST_SIGNATURE = "guest_signature"
CATEGORY_FAILED_ATTEMPT = "failed_attempt"
CATEGORY_SHIELD_MODE = "shield_mode"
CATEGORY_DEAD_MANS_SWITCH = "dead_mans_switch"
CATEGORY_BILLING = "billing"
CATEGORY_VERIFY_ATTEMPT = "verify_attempt"
CATEGORY_PRESENCE = "presence"
CATEGORY_TENANT_ASSIGNMENT = "tenant_assignment"

# Column limits (match model)
_CATEGORY_LEN = 32
_TITLE_LEN = 255
_ACTOR_EMAIL_LEN = 255
_IP_LEN = 64
_USER_AGENT_LEN = 500
_MESSAGE_LEN = 100_000  # avoid unbounded Text blobs


def _sanitize_meta_value(v: Any) -> Any:
    """Convert to JSON-serializable value so meta never raises on INSERT."""
    if v is None:
        return None
    if isinstance(v, (str, int, float, bool)):
        return v
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if isinstance(v, enum.Enum):
        return getattr(v, "value", str(v))
    if isinstance(v, dict):
        return {str(k): _sanitize_meta_value(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_sanitize_meta_value(x) for x in v]
    return str(v)


def _sanitize_meta(meta: dict[str, Any] | None) -> dict[str, Any] | None:
    if meta is None:
        return None
    try:
        return {str(k): _sanitize_meta_value(v) for k, v in meta.items()}
    except Exception:
        return {"_error": "meta_serialization", "raw_keys": list(meta.keys())[:10]}


_ACTING_ROLE_LABELS: dict[UserRole, str] = {
    UserRole.owner: "Owner",
    UserRole.property_manager: "Manager",
    UserRole.tenant: "Tenant",
    UserRole.guest: "Guest",
    UserRole.admin: "Admin",
}


def infer_acting_role_label(db: Session, actor_user_id: int | None) -> str | None:
    """Human-readable acting role for audit display (from users.role)."""
    if not actor_user_id:
        return None
    u = db.query(User).filter(User.id == actor_user_id).first()
    if not u or u.role is None:
        return None
    return _ACTING_ROLE_LABELS.get(u.role)


def infer_lane_context(
    db: Session,
    *,
    property_id: int | None = None,
    stay_id: int | None = None,
    invitation_id: int | None = None,
) -> str | None:
    """
    Coarse lane for the event: tenant-invited guest vs property/management business lane vs property-only.
    Stay-linked events take precedence over invitation-only.
    """
    if stay_id is not None:
        stay = db.query(Stay).filter(Stay.id == stay_id).first()
        if stay is None:
            return None
        if is_tenant_lane_stay(db, stay):
            return "tenant_lane"
        return "business_lane"
    if invitation_id is not None:
        inv = db.query(Invitation).filter(Invitation.id == invitation_id).first()
        if inv is None:
            return None
        if is_tenant_lane_invitation(db, inv):
            return "tenant_lane"
        return "business_lane"
    if property_id is not None:
        return "property_level"
    return None


def create_log(
    db: Session,
    category: str,
    title: str,
    message: str,
    *,
    property_id: int | None = None,
    stay_id: int | None = None,
    invitation_id: int | None = None,
    actor_user_id: int | None = None,
    actor_email: str | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    meta: dict[str, Any] | None = None,
    acting_role: str | None = None,
    lane_context: str | None = None,
) -> AuditLog | None:
    """Append one immutable audit log record. All timestamps are UTC (server_default).
    String fields are truncated to column limits; meta is sanitized for JSON.

    ``acting_role`` and ``lane_context`` are stored under meta keys ``acting_role`` and
    ``lane_context`` (e.g. Owner / tenant_lane). When omitted, they are inferred from
    ``actor_user_id`` and stay/invitation/property scope when possible.
    Returns None when the property is inactive (soft-deleted) — no new logs for unmanaged properties."""
    from app.services.property_scope import suppress_new_audit_for_inactive_property

    if suppress_new_audit_for_inactive_property(
        db, property_id=property_id, stay_id=stay_id, invitation_id=invitation_id
    ):
        return None
    cat = (category or "")[: _CATEGORY_LEN].strip() or "status_change"
    tit = (title or "")[: _TITLE_LEN].strip() or "—"
    msg = (message or "")[: _MESSAGE_LEN].strip() or "—"
    actor_em: str | None = None
    if actor_user_id:
        from app.services.event_ledger import get_actor_display_name

        actor_em = (get_actor_display_name(db, actor_user_id) or "")[: _ACTOR_EMAIL_LEN] or None
    if not actor_em and actor_email:
        from app.services.event_ledger import _display_name_for_email

        actor_em = (_display_name_for_email(db, actor_email) or "")[: _ACTOR_EMAIL_LEN] or None
    ip = (ip_address[: _IP_LEN] if ip_address else None) or None
    ua = (str(user_agent)[: _USER_AGENT_LEN] if user_agent else None) or None
    safe_meta = _sanitize_meta(meta)
    merged: dict[str, Any] = dict(safe_meta or {})
    ar = (acting_role or "").strip()[:64] or None
    if ar:
        merged[META_ACTING_ROLE] = ar
    elif actor_user_id and META_ACTING_ROLE not in merged:
        inferred_role = infer_acting_role_label(db, actor_user_id)
        if inferred_role:
            merged[META_ACTING_ROLE] = inferred_role
    lc = (lane_context or "").strip()[:64] or None
    if lc:
        merged[META_LANE_CONTEXT] = lc
    elif META_LANE_CONTEXT not in merged:
        inferred_lane = infer_lane_context(
            db, property_id=property_id, stay_id=stay_id, invitation_id=invitation_id
        )
        if inferred_lane:
            merged[META_LANE_CONTEXT] = inferred_lane
    final_meta = _sanitize_meta(merged) if merged else None

    entry = AuditLog(
        category=cat,
        title=tit,
        message=msg,
        property_id=property_id,
        stay_id=stay_id,
        invitation_id=invitation_id,
        actor_user_id=actor_user_id,
        actor_email=actor_em,
        ip_address=ip,
        user_agent=ua,
        meta=final_meta,
    )
    db.add(entry)
    db.flush()  # get entry.id if caller needs it; commit remains with caller
    return entry
