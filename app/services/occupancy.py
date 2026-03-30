"""Shared occupancy logic for owner and manager views.

Units are considered effectively "occupied" when:
- the unit's stored occupancy_status is "occupied", or
- the unit has an on-site resident (ResidentMode with manager_personal).

This ensures both owner and manager see the same status for units where
a property manager is assigned as on-site resident.
"""
from datetime import date

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.owner import OccupancyStatus
from app.models.resident_mode import ResidentMode, ResidentModeType
from app.models.unit import Unit
from app.models.stay import Stay
from app.models.invitation import Invitation
from app.models.user import User
from app.models.tenant_assignment import TenantAssignment
from app.services.privacy_lanes import is_tenant_lane_invitation, is_tenant_lane_stay
from app.services.display_names import label_from_invitation, label_from_user_id


def is_unit_effectively_occupied(db: Session, unit: Unit) -> bool:
    """True if the unit is occupied (stored status) or has an on-site resident (ResidentMode)."""
    if (unit.occupancy_status or "").lower() == OccupancyStatus.occupied.value:
        return True
    return (
        db.query(ResidentMode)
        .filter(
            ResidentMode.unit_id == unit.id,
            ResidentMode.mode == ResidentModeType.manager_personal,
        )
        .first()
        is not None
    )


def get_unit_display_occupancy_status(db: Session, unit: Unit) -> str:
    """Return the occupancy status to display for a unit (owner or manager view)."""
    if (unit.occupancy_status or "").lower() == OccupancyStatus.occupied.value:
        return OccupancyStatus.occupied.value
    if (
        db.query(ResidentMode)
        .filter(
            ResidentMode.unit_id == unit.id,
            ResidentMode.mode == ResidentModeType.manager_personal,
        )
        .first()
        is not None
    ):
        return OccupancyStatus.occupied.value
    return unit.occupancy_status or OccupancyStatus.unknown.value


def count_effectively_occupied_units(db: Session, units: list[Unit]) -> int:
    """Count how many units are effectively occupied (stored or on-site resident)."""
    return sum(1 for u in units if is_unit_effectively_occupied(db, u))


def get_property_display_occupancy_status(
    db: Session, prop, units: list[Unit]
) -> str:
    """Return property-level occupancy status for display (occupied if any unit is effectively occupied)."""
    if not units:
        return prop.occupancy_status or OccupancyStatus.unknown.value
    occupied_count = count_effectively_occupied_units(db, units)
    if occupied_count > 0:
        return OccupancyStatus.occupied.value
    return prop.occupancy_status or OccupancyStatus.unknown.value


def get_units_occupancy_display(
    db: Session,
    unit_ids: list[int],
    anonymize_tenant_lane: bool = False,
    guest_detail_unit_ids: set[int] | None = None,
) -> dict[int, dict]:
    """
    For each unit_id, return { "occupied_by": str | None, "invite_id": str | None }.
    Priority: active guest stay (with invite_id) > pending invitation > property manager resident > tenant.
    When anonymize_tenant_lane=True (owner/manager view), tenant-invited guest names are shown as "Occupied"
    and invite_id is omitted (tenant guest activity is private).
    When guest_detail_unit_ids is set (e.g. owner personal mode), guest stays/invites are only included for
    those units — not for units the owner rents out (tenant guest flow stays private).
    """
    if not unit_ids:
        return {}
    today = date.today()
    out = {uid: {"occupied_by": None, "invite_id": None} for uid in unit_ids}

    # Active stays (guest checked in, not out, not cancelled)
    stays = (
        db.query(Stay)
        .filter(
            Stay.unit_id.in_(unit_ids),
            Stay.checked_in_at.isnot(None),
            Stay.checked_out_at.is_(None),
            Stay.cancelled_at.is_(None),
        )
        .all()
    )
    inv_ids = [s.invitation_id for s in stays if s.invitation_id]
    invitations_by_id = {}
    if inv_ids:
        invs = db.query(Invitation).filter(Invitation.id.in_(inv_ids)).all()
        invitations_by_id = {i.id: i for i in invs}
    guest_user_ids = list({s.guest_id for s in stays})
    users_by_id = {}
    if guest_user_ids:
        users = db.query(User).filter(User.id.in_(guest_user_ids)).all()
        users_by_id = {u.id: u for u in users}
    for s in stays:
        if s.unit_id not in out:
            continue
        if guest_detail_unit_ids is not None and s.unit_id not in guest_detail_unit_ids:
            continue
        inv = invitations_by_id.get(s.invitation_id) if s.invitation_id else None
        if anonymize_tenant_lane and is_tenant_lane_stay(db, s):
            name = "Occupied"
            inv_code = None
        else:
            guest_user = users_by_id.get(s.guest_id)
            name = None
            if inv:
                name = label_from_invitation(db, inv)
            elif guest_user or s.guest_id:
                name = label_from_user_id(db, s.guest_id)
            if not name:
                name = "Unknown invitee"
            inv_code = inv.invitation_code if inv else None
        out[s.unit_id] = {
            "occupied_by": name,
            "invite_id": inv_code,
        }

    # Pending invitations (STAGED) for units not yet filled by a stay
    still_empty = [uid for uid in unit_ids if out[uid]["occupied_by"] is None]
    if still_empty:
        invs = (
            db.query(Invitation)
            .filter(
                Invitation.unit_id.in_(still_empty),
                Invitation.token_state == "STAGED",
            )
            .all()
        )
        for inv in invs:
            if inv.unit_id not in out or out[inv.unit_id]["occupied_by"] is not None:
                continue
            if guest_detail_unit_ids is not None and inv.unit_id not in guest_detail_unit_ids:
                continue
            if anonymize_tenant_lane and is_tenant_lane_invitation(db, inv):
                name = "Occupied"
                inv_code = None
            else:
                name = label_from_invitation(db, inv)
                inv_code = inv.invitation_code
            out[inv.unit_id] = {"occupied_by": name, "invite_id": inv_code}

    # Property manager on-site resident
    still_empty = [uid for uid in unit_ids if out[uid]["occupied_by"] is None]
    if still_empty:
        modes = (
            db.query(ResidentMode)
            .filter(
                ResidentMode.unit_id.in_(still_empty),
                ResidentMode.mode == ResidentModeType.manager_personal,
            )
            .all()
        )
        manager_ids = list({m.user_id for m in modes})
        users_by_id = {}
        if manager_ids:
            users = db.query(User).filter(User.id.in_(manager_ids)).all()
            users_by_id = {u.id: u for u in users}
        for m in modes:
            if m.unit_id not in out or out[m.unit_id]["occupied_by"] is not None:
                continue
            u = users_by_id.get(m.user_id)
            base = (u.full_name or "").strip() or (u.email if u else "") or "Property manager"
            name = f"{base} (Property manager)" if "(Property manager)" not in base else base
            out[m.unit_id] = {"occupied_by": name, "invite_id": None}

    # Tenant assignment (current: end_date null or >= today)
    still_empty = [uid for uid in unit_ids if out[uid]["occupied_by"] is None]
    if still_empty:
        assignments = (
            db.query(TenantAssignment)
            .filter(
                TenantAssignment.unit_id.in_(still_empty),
                or_(
                    TenantAssignment.end_date.is_(None),
                    TenantAssignment.end_date >= today,
                ),
            )
            .all()
        )
        tenant_ids = list({a.user_id for a in assignments})
        users_by_id = {}
        if tenant_ids:
            users = db.query(User).filter(User.id.in_(tenant_ids)).all()
            users_by_id = {u.id: u for u in users}
        for a in assignments:
            if a.unit_id not in out or out[a.unit_id]["occupied_by"] is not None:
                continue
            u = users_by_id.get(a.user_id)
            name = (u.full_name or "").strip() or (u.email if u else "Tenant")
            out[a.unit_id] = {"occupied_by": name, "invite_id": None}

    return out


def get_units_occupancy_sources(
    db: Session,
    unit_ids: list[int],
    *,
    guest_detail_unit_ids: set[int] | None = None,
) -> dict[int, str]:
    """
    Per unit, which tier supplies display occupancy (same priority as get_units_occupancy_display):
    guest_stay | pending_invitation | manager_resident | tenant_assignment | none.
    Used by the public live page tenant summary so it shows the leaseholder tenant only when they
    are the effective occupier (not superseded by a checked-in guest stay, pending invite, or
    on-site manager resident).
    """
    if not unit_ids:
        return {}
    today = date.today()
    out = {uid: "none" for uid in unit_ids}

    stays = (
        db.query(Stay)
        .filter(
            Stay.unit_id.in_(unit_ids),
            Stay.checked_in_at.isnot(None),
            Stay.checked_out_at.is_(None),
            Stay.cancelled_at.is_(None),
        )
        .all()
    )
    for s in stays:
        if s.unit_id not in out:
            continue
        if guest_detail_unit_ids is not None and s.unit_id not in guest_detail_unit_ids:
            continue
        out[s.unit_id] = "guest_stay"

    still_empty = [uid for uid in unit_ids if out[uid] == "none"]
    if still_empty:
        invs = (
            db.query(Invitation)
            .filter(
                Invitation.unit_id.in_(still_empty),
                Invitation.token_state == "STAGED",
            )
            .all()
        )
        for inv in invs:
            if inv.unit_id not in out or out[inv.unit_id] != "none":
                continue
            if guest_detail_unit_ids is not None and inv.unit_id not in guest_detail_unit_ids:
                continue
            out[inv.unit_id] = "pending_invitation"

    still_empty = [uid for uid in unit_ids if out[uid] == "none"]
    if still_empty:
        modes = (
            db.query(ResidentMode)
            .filter(
                ResidentMode.unit_id.in_(still_empty),
                ResidentMode.mode == ResidentModeType.manager_personal,
            )
            .all()
        )
        for m in modes:
            if m.unit_id not in out or out[m.unit_id] != "none":
                continue
            out[m.unit_id] = "manager_resident"

    still_empty = [uid for uid in unit_ids if out[uid] == "none"]
    if still_empty:
        assignments = (
            db.query(TenantAssignment)
            .filter(
                TenantAssignment.unit_id.in_(still_empty),
                or_(
                    TenantAssignment.end_date.is_(None),
                    TenantAssignment.end_date >= today,
                ),
            )
            .all()
        )
        for a in assignments:
            if a.unit_id not in out or out[a.unit_id] != "none":
                continue
            out[a.unit_id] = "tenant_assignment"

    return out
