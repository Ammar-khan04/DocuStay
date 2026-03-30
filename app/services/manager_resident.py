"""Shared logic: property manager on-site resident (ResidentMode / Personal Mode for a unit).

Can be initiated by the owner or by the manager (self-service) when they are assigned to the property."""
from __future__ import annotations

from fastapi import HTTPException, Request
from sqlalchemy.orm import Session

from app.models.owner import OccupancyStatus, Property
from app.models.property_manager_assignment import PropertyManagerAssignment
from app.models.resident_mode import ResidentMode, ResidentModeType
from app.models.stay import Stay
from app.models.unit import Unit
from app.models.user import User
from app.services.event_ledger import (
    create_ledger_event,
    ACTION_MANAGER_ONSITE_RESIDENT_ADDED,
    ACTION_MANAGER_ONSITE_RESIDENT_REMOVED,
)


def resolve_unit_id_for_property(
    db: Session,
    property_id: int,
    unit_id: int | None,
    prop: Property,
) -> int:
    """Return a real Unit.id. Accepts unit_id from client; if 0/missing, use sole unit or create one for single-unit properties."""
    if unit_id is not None and unit_id > 0:
        u = db.query(Unit).filter(Unit.id == unit_id, Unit.property_id == property_id).first()
        if not u:
            raise HTTPException(status_code=404, detail="Unit not found or does not belong to this property.")
        return unit_id
    units = db.query(Unit).filter(Unit.property_id == property_id).order_by(Unit.id).all()
    if len(units) == 1:
        return units[0].id
    if len(units) == 0 and not getattr(prop, "is_multi_unit", False):
        u = Unit(
            property_id=property_id,
            unit_label="1",
            occupancy_status=prop.occupancy_status or OccupancyStatus.unknown.value,
        )
        db.add(u)
        db.flush()
        return u.id
    raise HTTPException(
        status_code=400,
        detail="Select which unit you live in. This property has multiple units.",
    )


def add_manager_onsite_resident(
    db: Session,
    property_id: int,
    manager_user_id: int,
    unit_id: int | None,
    *,
    actor_user_id: int,
    initiator: str,
    request: Request | None,
) -> dict:
    """
    Create ResidentMode for manager at unit. initiator: 'owner' | 'manager' (for ledger copy only).
    """
    prop = db.query(Property).filter(Property.id == property_id, Property.deleted_at.is_(None)).first()
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")

    assn = db.query(PropertyManagerAssignment).filter(
        PropertyManagerAssignment.property_id == property_id,
        PropertyManagerAssignment.user_id == manager_user_id,
    ).first()
    if not assn:
        raise HTTPException(status_code=404, detail="Manager is not assigned to this property.")

    resolved_unit_id = resolve_unit_id_for_property(db, property_id, unit_id, prop)

    existing_same_property = (
        db.query(ResidentMode)
        .join(Unit, ResidentMode.unit_id == Unit.id)
        .filter(
            ResidentMode.user_id == manager_user_id,
            ResidentMode.mode == ResidentModeType.manager_personal,
            Unit.property_id == property_id,
        )
        .all()
    )
    for rm in existing_same_property:
        if rm.unit_id == resolved_unit_id:
            return {
                "status": "success",
                "message": "Already registered as on-site resident for this unit."
                if initiator == "manager"
                else "Manager already has Personal Mode for this unit.",
                "unit_id": resolved_unit_id,
            }
    if existing_same_property:
        raise HTTPException(
            status_code=400,
            detail="You are already registered as on-site resident for another unit at this property. Remove that first, or ask the owner to adjust.",
        )

    unit = db.query(Unit).filter(Unit.id == resolved_unit_id, Unit.property_id == property_id).first()
    if not unit:
        raise HTTPException(status_code=404, detail="Unit not found.")

    rm = ResidentMode(
        user_id=manager_user_id,
        unit_id=resolved_unit_id,
        mode=ResidentModeType.manager_personal,
    )
    db.add(rm)
    db.flush()

    unit.occupancy_status = OccupancyStatus.occupied.value
    if prop.is_multi_unit:
        units = db.query(Unit).filter(Unit.property_id == property_id).all()
        occupied_count = sum(1 for u in units if (u.occupancy_status or "").lower() == OccupancyStatus.occupied.value)
        prop.occupancy_status = OccupancyStatus.occupied.value if occupied_count > 0 else OccupancyStatus.vacant.value
    else:
        prop.occupancy_status = OccupancyStatus.occupied.value

    mgr = db.query(User).filter(User.id == manager_user_id).first()
    mgr_email = (mgr.email or "").strip() if mgr else None
    prop_name = (prop.name or f"{prop.street}, {prop.city}").strip() or f"Property {property_id}"
    unit_label = (unit.unit_label or "").strip() or str(resolved_unit_id)
    ip = request.client.host if request and request.client else None
    ua = (request.headers.get("user-agent") or "").strip() if request else None

    if initiator == "manager":
        msg = (
            f"Property manager {mgr_email or manager_user_id} registered as on-site resident for Unit {unit_label} "
            f"at {prop_name} (self-service; Personal Mode for that unit)."
        )
    else:
        msg = (
            f"Property manager {mgr_email or manager_user_id} added as on-site resident for Unit {unit_label} "
            f"at {prop_name} (Personal Mode for that unit)."
        )

    create_ledger_event(
        db,
        ACTION_MANAGER_ONSITE_RESIDENT_ADDED,
        target_object_type="ResidentMode",
        target_object_id=rm.id,
        property_id=property_id,
        unit_id=resolved_unit_id,
        actor_user_id=actor_user_id,
        meta={
            "message": msg,
            "manager_user_id": manager_user_id,
            "manager_email": mgr_email,
            "unit_id": resolved_unit_id,
            "unit_label": unit_label,
            "initiated_by": initiator,
        },
        ip_address=ip,
        user_agent=ua,
    )
    db.commit()
    return {
        "status": "success",
        "message": "You are now registered as on-site resident for this unit. Switch to Personal mode to set presence and use guest features for your unit."
        if initiator == "manager"
        else "Manager added as on-site resident. They now have Personal Mode for this unit.",
        "unit_id": resolved_unit_id,
    }


def remove_manager_onsite_resident(
    db: Session,
    property_id: int,
    manager_user_id: int,
    *,
    actor_user_id: int,
    initiator: str,
    request: Request | None,
) -> dict:
    """Remove ResidentMode for manager on this property. initiator: 'owner' | 'manager'."""
    prop = db.query(Property).filter(Property.id == property_id, Property.deleted_at.is_(None)).first()
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")

    resident = (
        db.query(ResidentMode)
        .join(Unit, ResidentMode.unit_id == Unit.id)
        .filter(
            ResidentMode.user_id == manager_user_id,
            ResidentMode.mode == ResidentModeType.manager_personal,
            Unit.property_id == property_id,
        )
        .first()
    )
    if not resident:
        raise HTTPException(status_code=404, detail="No on-site resident registration found for this property.")

    unit_id = resident.unit_id
    resident_id = resident.id
    mgr = db.query(User).filter(User.id == manager_user_id).first()
    mgr_email = (mgr.email or "").strip() if mgr else None
    unit_row = db.query(Unit).filter(Unit.id == unit_id).first()
    unit_label = (unit_row.unit_label or "").strip() if unit_row else str(unit_id)
    prop_name = (prop.name or f"{prop.street}, {prop.city}").strip() or f"Property {property_id}"
    ip = request.client.host if request and request.client else None
    ua = (request.headers.get("user-agent") or "").strip() if request else None

    if initiator == "manager":
        msg = (
            f"Property manager {mgr_email or manager_user_id} removed their on-site resident registration for Unit {unit_label} "
            f"at {prop_name} (self-service; management assignment unchanged)."
        )
    else:
        msg = (
            f"Property manager {mgr_email or manager_user_id} removed as on-site resident for Unit {unit_label} "
            f"at {prop_name} (Personal Mode link removed; manager assignment unchanged)."
        )

    create_ledger_event(
        db,
        ACTION_MANAGER_ONSITE_RESIDENT_REMOVED,
        target_object_type="ResidentMode",
        target_object_id=resident_id,
        property_id=property_id,
        unit_id=unit_id,
        actor_user_id=actor_user_id,
        meta={
            "message": msg,
            "manager_user_id": manager_user_id,
            "manager_email": mgr_email,
            "unit_id": unit_id,
            "unit_label": unit_label,
            "initiated_by": initiator,
        },
        ip_address=ip,
        user_agent=ua,
    )
    db.delete(resident)

    unit = db.query(Unit).filter(Unit.id == unit_id).first()
    if unit:
        has_active_stay = (
            db.query(Stay)
            .filter(
                Stay.unit_id == unit_id,
                Stay.checked_in_at.isnot(None),
                Stay.checked_out_at.is_(None),
                Stay.cancelled_at.is_(None),
            )
            .first()
        ) is not None
        if not has_active_stay:
            unit.occupancy_status = OccupancyStatus.vacant.value
        if prop.is_multi_unit:
            units = db.query(Unit).filter(Unit.property_id == property_id).all()
            occupied_count = sum(1 for u in units if (u.occupancy_status or "").lower() == OccupancyStatus.occupied.value)
            prop.occupancy_status = OccupancyStatus.occupied.value if occupied_count > 0 else OccupancyStatus.vacant.value
        else:
            prop.occupancy_status = OccupancyStatus.vacant.value if not has_active_stay else prop.occupancy_status

    db.commit()
    return {
        "status": "success",
        "message": "Your on-site resident registration was removed. You remain assigned as property manager."
        if initiator == "manager"
        else "Manager removed as on-site resident. They remain assigned as manager; the unit is now vacant (if no active stay).",
    }
