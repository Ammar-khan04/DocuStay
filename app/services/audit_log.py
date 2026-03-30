"""Append-only audit log service. Never update or delete - immutable audit trail."""
from __future__ import annotations

import enum
from datetime import date, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog

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
) -> AuditLog:
    """Append one immutable audit log record. All timestamps are UTC (server_default).
    String fields are truncated to column limits; meta is sanitized for JSON."""
    cat = (category or "")[: _CATEGORY_LEN].strip() or "status_change"
    tit = (title or "")[: _TITLE_LEN].strip() or "—"
    msg = (message or "")[: _MESSAGE_LEN].strip() or "—"
    actor_em = (actor_email[: _ACTOR_EMAIL_LEN] if actor_email else None) or None
    ip = (ip_address[: _IP_LEN] if ip_address else None) or None
    ua = (str(user_agent)[: _USER_AGENT_LEN] if user_agent else None) or None
    safe_meta = _sanitize_meta(meta)

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
        meta=safe_meta,
    )
    db.add(entry)
    db.flush()  # get entry.id if caller needs it; commit remains with caller
    return entry
