"""One open guest stay per (guest, property, unit) for overlapping calendar dates.

Overlaps use inclusive date ranges. Open stays are those not checked out and not cancelled.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.invitation import Invitation
from app.models.stay import Stay


def guest_stay_dates_overlap_inclusive(a_start: date, a_end: date, b_start: date, b_end: date) -> bool:
    return a_start <= b_end and a_end >= b_start


def list_open_overlapping_guest_stays(
    db: Session,
    *,
    guest_id: int,
    property_id: int,
    unit_id: int | None,
    range_start: date,
    range_end: date,
    exclude_stay_id: int | None = None,
) -> list[Stay]:
    q = db.query(Stay).filter(
        Stay.guest_id == guest_id,
        Stay.property_id == property_id,
        Stay.checked_out_at.is_(None),
        Stay.cancelled_at.is_(None),
        Stay.stay_start_date <= range_end,
        Stay.stay_end_date >= range_start,
    )
    if unit_id is None:
        q = q.filter(Stay.unit_id.is_(None))
    else:
        q = q.filter(Stay.unit_id == unit_id)
    if exclude_stay_id is not None:
        q = q.filter(Stay.id != exclude_stay_id)
    return q.all()


def cancel_superseded_open_guest_stay(db: Session, stay: Stay, *, now: datetime | None = None) -> None:
    """Close an unchecked-in overlapping stay so a new acceptance can proceed; align invitation token."""
    if now is None:
        now = datetime.now(timezone.utc)
    original_start = stay.stay_start_date
    stay.stay_end_date = original_start - timedelta(days=1)
    stay.cancelled_at = now
    iid = getattr(stay, "invitation_id", None)
    if iid:
        inv = db.query(Invitation).filter(Invitation.id == iid).first()
        if inv:
            inv.token_state = "REVOKED"
    db.add(stay)


def enforce_guest_stay_no_overlap_or_resolve_for_dates(
    db: Session,
    *,
    guest_id: int,
    property_id: int,
    unit_id: int | None,
    range_start: date,
    range_end: date,
) -> None:
    """
    Before creating a Stay:
    - If any overlapping open stay on the same unit has been checked in, raise HTTP 409.
    - Otherwise auto-cancel overlapping open stays (superseded by the new authorization).
    """
    from fastapi import HTTPException

    conflicts = list_open_overlapping_guest_stays(
        db,
        guest_id=guest_id,
        property_id=property_id,
        unit_id=unit_id,
        range_start=range_start,
        range_end=range_end,
    )
    if not conflicts:
        return
    if any(getattr(s, "checked_in_at", None) is not None for s in conflicts):
        raise HTTPException(
            status_code=409,
            detail="You already have an active stay that overlaps these dates for this unit. Check out or wait until it ends before accepting another invitation.",
        )
    now = datetime.now(timezone.utc)
    for s in conflicts:
        cancel_superseded_open_guest_stay(db, s, now=now)
    db.flush()


def enforce_guest_stay_no_overlap_or_resolve(db: Session, *, guest_id: int, inv: Invitation) -> None:
    enforce_guest_stay_no_overlap_or_resolve_for_dates(
        db,
        guest_id=guest_id,
        property_id=inv.property_id,
        unit_id=getattr(inv, "unit_id", None),
        range_start=inv.stay_start_date,
        range_end=inv.stay_end_date,
    )


def other_open_guest_stay_on_same_unit(
    db: Session,
    *,
    property_id: int,
    unit_id: int | None,
    exclude_stay_id: int,
) -> Stay | None:
    """Any stay on the same unit (including future / not checked in) still open."""
    q = db.query(Stay).filter(
        Stay.property_id == property_id,
        Stay.id != exclude_stay_id,
        Stay.checked_out_at.is_(None),
        Stay.cancelled_at.is_(None),
    )
    if unit_id is None:
        q = q.filter(Stay.unit_id.is_(None))
    else:
        q = q.filter(Stay.unit_id == unit_id)
    return q.first()


def other_checked_in_guest_stay_on_property(
    db: Session,
    *,
    property_id: int,
    exclude_stay_id: int,
) -> Stay | None:
    """Another guest stay on this property that is checked in and not closed."""
    return (
        db.query(Stay)
        .filter(
            Stay.property_id == property_id,
            Stay.id != exclude_stay_id,
            Stay.checked_in_at.isnot(None),
            Stay.checked_out_at.is_(None),
            Stay.cancelled_at.is_(None),
        )
        .first()
    )


def other_checked_in_guest_stay_on_same_unit(
    db: Session,
    *,
    property_id: int,
    unit_id: int | None,
    exclude_stay_id: int,
) -> Stay | None:
    """Another checked-in open stay on the same unit (NULL unit matches NULL only)."""
    q = db.query(Stay).filter(
        Stay.property_id == property_id,
        Stay.id != exclude_stay_id,
        Stay.checked_in_at.isnot(None),
        Stay.checked_out_at.is_(None),
        Stay.cancelled_at.is_(None),
    )
    if unit_id is None:
        q = q.filter(Stay.unit_id.is_(None))
    else:
        q = q.filter(Stay.unit_id == unit_id)
    return q.first()
