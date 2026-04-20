"""Helpers for soft-deleted (inactive) properties: no new audit/ledger/alerts/automation."""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.owner import Property
from app.models.stay import Stay
from app.models.invitation import Invitation


def property_is_managed_by_docustay(db: Session, property_id: int) -> bool:
    """False if property is missing or owner marked it inactive (deleted_at set)."""
    row = db.query(Property.deleted_at).filter(Property.id == property_id).first()
    return row is not None and row.deleted_at is None


def resolved_property_id_for_audit(
    db: Session,
    *,
    property_id: int | None,
    stay_id: int | None,
    invitation_id: int | None,
) -> int | None:
    if property_id is not None:
        return property_id
    if stay_id is not None:
        st = db.query(Stay).filter(Stay.id == stay_id).first()
        return int(st.property_id) if st else None
    if invitation_id is not None:
        inv = db.query(Invitation).filter(Invitation.id == invitation_id).first()
        return int(inv.property_id) if inv else None
    return None


def suppress_new_audit_for_inactive_property(
    db: Session,
    *,
    property_id: int | None = None,
    stay_id: int | None = None,
    invitation_id: int | None = None,
) -> bool:
    """True when this write should be skipped (inactive / unmanaged property scope)."""
    pid = resolved_property_id_for_audit(
        db, property_id=property_id, stay_id=stay_id, invitation_id=invitation_id
    )
    if pid is None:
        return False
    return not property_is_managed_by_docustay(db, pid)
