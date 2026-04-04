"""Shared rules for tenant lease windows on a unit: active invitations + TenantAssignment rows.

Used when creating tenant invites (owner/manager) and when recording a TenantAssignment (accept / register).
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.invitation import Invitation
from app.models.tenant_assignment import TenantAssignment
from app.models.user import User
from app.services.invitation_kinds import (
    TENANT_UNIT_LEASE_KINDS,
    bypasses_unit_lease_overlap_for_kind,
)


def _active_tenant_invitation_filters():
    """Invitations that still compete for the unit calendar (standard + co-tenant windows)."""
    return (
        Invitation.invitation_kind.in_(tuple(TENANT_UNIT_LEASE_KINDS)),
        Invitation.status.in_(("pending", "ongoing")),
        Invitation.token_state.notin_(("CANCELLED", "REVOKED", "EXPIRED")),
    )


def first_overlapping_tenant_invitation(
    db: Session,
    range_start: date,
    range_end: date,
    *,
    unit_id: int | None = None,
    property_id: int | None = None,
    exclude_invitation_id: int | None = None,
) -> Invitation | None:
    """Exactly one of unit_id or property_id: which dimension to scan for overlapping tenant invites."""
    if (unit_id is None) == (property_id is None):
        raise ValueError("Set exactly one of unit_id or property_id for invitation overlap")
    scope = Invitation.property_id == property_id if property_id is not None else Invitation.unit_id == unit_id
    q = db.query(Invitation).filter(
        scope,
        *_active_tenant_invitation_filters(),
        Invitation.stay_start_date <= range_end,
        Invitation.stay_end_date >= range_start,
    )
    if exclude_invitation_id is not None:
        q = q.filter(Invitation.id != exclude_invitation_id)
    return q.first()


def first_overlapping_tenant_assignment_for_unit(
    db: Session,
    unit_id: int,
    range_start: date,
    range_end: date,
) -> TenantAssignment | None:
    return (
        db.query(TenantAssignment)
        .filter(
            TenantAssignment.unit_id == unit_id,
            TenantAssignment.start_date <= range_end,
            or_(TenantAssignment.end_date.is_(None), TenantAssignment.end_date >= range_start),
        )
        .first()
    )


def unit_tenant_lease_conflict_detail(
    db: Session,
    unit_id: int,
    range_start: date,
    range_end: date,
    *,
    invitation_overlap_property_id: int | None = None,
    exclude_invitation_id: int | None = None,
    skip_overlap_check: bool = False,
) -> str | None:
    """Human-readable 409 detail, or None if the window is free for a new invite."""
    if skip_overlap_check:
        return None
    if invitation_overlap_property_id is not None:
        oi = first_overlapping_tenant_invitation(
            db,
            range_start,
            range_end,
            property_id=invitation_overlap_property_id,
            exclude_invitation_id=exclude_invitation_id,
        )
    else:
        oi = first_overlapping_tenant_invitation(
            db,
            range_start,
            range_end,
            unit_id=unit_id,
            exclude_invitation_id=exclude_invitation_id,
        )
    if oi:
        name = oi.guest_name or "another tenant"
        return (
            f"A tenant lease invitation already exists for this unit that overlaps the selected dates "
            f"({oi.stay_start_date.isoformat()} – {oi.stay_end_date.isoformat()}, {name}). "
            "Choose dates that do not overlap or cancel the existing invitation."
        )
    oa = first_overlapping_tenant_assignment_for_unit(db, unit_id, range_start, range_end)
    if oa:
        u = db.query(User).filter(User.id == oa.user_id).first()
        label = (u.email or "").strip() or f"user {oa.user_id}"
        return (
            f"A tenant is already assigned to this unit for dates that overlap your selection "
            f"({oa.start_date.isoformat()} – {(oa.end_date.isoformat() if oa.end_date else 'ongoing')}, {label}). "
            "Adjust lease dates or end the existing assignment before adding another lease."
        )
    return None


def assert_unit_available_for_new_tenant_invite_or_raise(
    db: Session,
    unit_id: int,
    range_start: date,
    range_end: date,
    *,
    invitation_overlap_property_id: int | None = None,
    exclude_invitation_id: int | None = None,
    skip_overlap_check: bool = False,
) -> None:
    """Owner/manager: block creating a tenant invite if the unit already has a competing invite or assignment."""
    from fastapi import HTTPException

    detail = unit_tenant_lease_conflict_detail(
        db,
        unit_id,
        range_start,
        range_end,
        invitation_overlap_property_id=invitation_overlap_property_id,
        exclude_invitation_id=exclude_invitation_id,
        skip_overlap_check=skip_overlap_check,
    )
    if detail:
        raise HTTPException(status_code=409, detail=detail)


def assignment_matches_invitation_dates(ta: TenantAssignment, inv: Invitation) -> bool:
    if inv.unit_id is None or ta.unit_id != inv.unit_id:
        return False
    if ta.start_date != inv.stay_start_date:
        return False
    if ta.end_date is None and inv.stay_end_date is None:
        return True
    return ta.end_date == inv.stay_end_date


def find_invitation_matching_tenant_assignment(
    db: Session, ta: TenantAssignment, *, user_email_lower: str | None
) -> Invitation | None:
    """Resolve the accepted property-issued invite row for this assignment (stable when multiple tenants share a unit)."""
    kinds = tuple(TENANT_UNIT_LEASE_KINDS)
    q = db.query(Invitation).filter(
        Invitation.unit_id == ta.unit_id,
        Invitation.invitation_kind.in_(kinds),
        Invitation.status == "accepted",
        Invitation.stay_start_date == ta.start_date,
    )
    if ta.end_date is None:
        q = q.filter(Invitation.stay_end_date.is_(None))
    else:
        q = q.filter(Invitation.stay_end_date == ta.end_date)
    rows = q.order_by(Invitation.created_at.desc()).all()
    if not rows:
        return None
    if user_email_lower:
        for inv in rows:
            if (getattr(inv, "guest_email", None) or "").strip().lower() == user_email_lower:
                return inv
    return rows[0] if len(rows) == 1 else None


def find_tenant_assignment_matching_invitation(
    db: Session, user_id: int, inv: Invitation
) -> TenantAssignment | None:
    if inv.unit_id is None:
        return None
    for ta in (
        db.query(TenantAssignment)
        .filter(
            TenantAssignment.user_id == user_id,
            TenantAssignment.unit_id == inv.unit_id,
        )
        .all()
    ):
        if assignment_matches_invitation_dates(ta, inv):
            return ta
    return None


def assert_can_record_tenant_assignment_for_invite_or_raise(
    db: Session,
    inv: Invitation,
    accepting_user_id: int,
) -> None:
    """Block creating a TenantAssignment if the unit window is taken by another person or a different lease."""
    from fastapi import HTTPException

    if inv.unit_id is None:
        return
    if bypasses_unit_lease_overlap_for_kind(getattr(inv, "invitation_kind", None)):
        return
    overlapping = (
        db.query(TenantAssignment)
        .filter(
            TenantAssignment.unit_id == inv.unit_id,
            TenantAssignment.start_date <= inv.stay_end_date,
            or_(TenantAssignment.end_date.is_(None), TenantAssignment.end_date >= inv.stay_start_date),
        )
        .all()
    )
    for ta in overlapping:
        if ta.user_id == accepting_user_id and assignment_matches_invitation_dates(ta, inv):
            continue
        u = db.query(User).filter(User.id == ta.user_id).first()
        label = (u.email or "").strip() or f"user {ta.user_id}"
        raise HTTPException(
            status_code=409,
            detail=(
                f"This unit already has a tenant assignment that overlaps these dates "
                f"({ta.start_date.isoformat()} – {(ta.end_date.isoformat() if ta.end_date else 'ongoing')}, {label}). "
                "You cannot accept this invitation until that lease no longer overlaps."
            ),
        )
