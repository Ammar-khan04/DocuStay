"""Shared logic: property manager on-site resident (ResidentMode / Personal Mode for a unit).

Can be initiated by the owner or by the manager (self-service) when they are assigned to the property."""
from __future__ import annotations

from fastapi import HTTPException, Request
from sqlalchemy.orm import Session

from app.models.owner import OccupancyStatus, Property
from app.models.property_manager_assignment import PropertyManagerAssignment
from app.models.resident_mode import ResidentMode, ResidentModeType
from app.models.resident_presence import ResidentPresence
from app.models.stay import Stay
from app.models.unit import Unit
from app.models.user import User
from app.services.event_ledger import (
    create_ledger_event,
    ACTION_MANAGER_ONSITE_RESIDENT_ADDED,
    ACTION_MANAGER_ONSITE_RESIDENT_REMOVED,
    ACTION_MANAGER_REMOVED_FROM_PROPERTY,
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
            occupancy_status=prop.occupancy_status or OccupancyStatus.vacant.value,
        )
        db.add(u)
        db.flush()
        return u.id
    raise HTTPException(
        status_code=400,
        detail="Select which unit you live in. This property has multiple units.",
    )


def delete_manager_personal_modes_for_property(
    db: Session,
    property_id: int,
    manager_user_id: int,
    prop: Property,
) -> None:
    """Remove manager_personal ResidentMode rows for this user on this property; fix unit/property occupancy. No commit, no ledger."""
    residents = (
        db.query(ResidentMode)
        .join(Unit, ResidentMode.unit_id == Unit.id)
        .filter(
            ResidentMode.user_id == manager_user_id,
            ResidentMode.mode == ResidentModeType.manager_personal,
            Unit.property_id == property_id,
        )
        .all()
    )
    if not residents:
        return
    unit_ids = sorted({r.unit_id for r in residents})
    for r in residents:
        db.delete(r)
    for uid in unit_ids:
        pres = (
            db.query(ResidentPresence)
            .filter(
                ResidentPresence.user_id == manager_user_id,
                ResidentPresence.unit_id == uid,
            )
            .first()
        )
        if pres:
            db.delete(pres)
    for unit_id in unit_ids:
        unit = db.query(Unit).filter(Unit.id == unit_id).first()
        if not unit:
            continue
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
        units_all = db.query(Unit).filter(Unit.property_id == property_id).all()
        occupied_count = sum(
            1 for u in units_all if (u.occupancy_status or "").lower() == OccupancyStatus.occupied.value
        )
        prop.occupancy_status = OccupancyStatus.occupied.value if occupied_count > 0 else OccupancyStatus.vacant.value
    elif unit_ids:
        uid0 = unit_ids[0]
        has_active_stay = (
            db.query(Stay)
            .filter(
                Stay.unit_id == uid0,
                Stay.checked_in_at.isnot(None),
                Stay.checked_out_at.is_(None),
                Stay.cancelled_at.is_(None),
            )
            .first()
        ) is not None
        prop.occupancy_status = OccupancyStatus.vacant.value if not has_active_stay else prop.occupancy_status


def remove_other_property_managers_from_property(
    db: Session,
    property_id: int,
    keep_manager_user_id: int,
    *,
    actor_user_id: int,
    request: Request | None,
    prop: Property,
) -> int:
    """Delete every PropertyManagerAssignment on this property except keep_manager_user_id. Strips their manager_personal modes. Returns how many assignments were removed."""
    assignments = (
        db.query(PropertyManagerAssignment)
        .filter(
            PropertyManagerAssignment.property_id == property_id,
            PropertyManagerAssignment.user_id != keep_manager_user_id,
        )
        .all()
    )
    if not assignments:
        return 0
    prop_name = (prop.name or f"{prop.street}, {prop.city}").strip() or f"Property {property_id}"
    ip = request.client.host if request and request.client else None
    ua = (request.headers.get("user-agent") or "").strip() if request else None
    count = 0
    for assn in assignments:
        uid = assn.user_id
        delete_manager_personal_modes_for_property(db, property_id, uid, prop)
        mgr = db.query(User).filter(User.id == uid).first()
        mgr_email = (mgr.email or "").strip() if mgr else None
        create_ledger_event(
            db,
            ACTION_MANAGER_REMOVED_FROM_PROPERTY,
            target_object_type="PropertyManagerAssignment",
            target_object_id=assn.id,
            property_id=property_id,
            actor_user_id=actor_user_id,
            meta={
                "message": f"Property manager removed from {prop_name}: {mgr_email or uid} (removed because another manager was granted on-site access for all units).",
                "manager_user_id": uid,
                "manager_email": mgr_email,
                "reason": "all_units_onsite_for_other_manager",
            },
            ip_address=ip,
            user_agent=ua,
        )
        db.delete(assn)
        count += 1
    return count


def remove_all_property_managers_from_property(
    db: Session,
    property_id: int,
    *,
    actor_user_id: int,
    request: Request | None,
    prop: Property,
) -> int:
    """Delete every PropertyManagerAssignment on this property. Strips manager_personal modes. Returns how many were removed."""
    assignments = (
        db.query(PropertyManagerAssignment)
        .filter(PropertyManagerAssignment.property_id == property_id)
        .all()
    )
    if not assignments:
        return 0
    prop_name = (prop.name or f"{prop.street}, {prop.city}").strip() or f"Property {property_id}"
    ip = request.client.host if request and request.client else None
    ua = (request.headers.get("user-agent") or "").strip() if request else None
    count = 0
    for assn in assignments:
        uid = assn.user_id
        delete_manager_personal_modes_for_property(db, property_id, uid, prop)
        mgr = db.query(User).filter(User.id == uid).first()
        mgr_email = (mgr.email or "").strip() if mgr else None
        create_ledger_event(
            db,
            ACTION_MANAGER_REMOVED_FROM_PROPERTY,
            target_object_type="PropertyManagerAssignment",
            target_object_id=assn.id,
            property_id=property_id,
            actor_user_id=actor_user_id,
            meta={
                "message": (
                    f"Property manager removed from {prop_name}: {mgr_email or uid} "
                    "(removed because the owner invited a new manager for this single-unit property)."
                ),
                "manager_user_id": uid,
                "manager_email": mgr_email,
                "reason": "single_unit_manager_invite",
            },
            ip_address=ip,
            user_agent=ua,
        )
        db.delete(assn)
        count += 1
    return count


def add_manager_onsite_resident_all_units(
    db: Session,
    property_id: int,
    manager_user_id: int,
    *,
    actor_user_id: int,
    initiator: str,
    request: Request | None,
    confirm_remove_other_managers: bool = False,
) -> dict:
    """Create manager_personal ResidentMode for every unit on the property that does not already have one.

    Owner flow: if other managers are assigned, requires confirm_remove_other_managers=True or returns 409.
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

    units = db.query(Unit).filter(Unit.property_id == property_id).order_by(Unit.id).all()
    if not units:
        raise HTTPException(status_code=404, detail="No units on this property.")

    removed_other_manager_count = 0
    if initiator == "owner":
        other_assignments = (
            db.query(PropertyManagerAssignment)
            .filter(
                PropertyManagerAssignment.property_id == property_id,
                PropertyManagerAssignment.user_id != manager_user_id,
            )
            .count()
        )
        if other_assignments > 0:
            if not confirm_remove_other_managers:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "OTHER_MANAGERS_PRESENT: Assigning on-site access for all units removes every other "
                        "property manager from this property. Resend the request with confirm_remove_other_managers set to true to proceed."
                    ),
                )
            removed_other_manager_count = remove_other_property_managers_from_property(
                db,
                property_id,
                manager_user_id,
                actor_user_id=actor_user_id,
                request=request,
                prop=prop,
            )

    existing = (
        db.query(ResidentMode)
        .join(Unit, ResidentMode.unit_id == Unit.id)
        .filter(
            ResidentMode.user_id == manager_user_id,
            ResidentMode.mode == ResidentModeType.manager_personal,
            Unit.property_id == property_id,
        )
        .all()
    )
    existing_unit_ids = {rm.unit_id for rm in existing}

    added_rows: list[tuple[ResidentMode, Unit]] = []
    for unit in units:
        if unit.id in existing_unit_ids:
            continue
        rm = ResidentMode(
            user_id=manager_user_id,
            unit_id=unit.id,
            mode=ResidentModeType.manager_personal,
        )
        db.add(rm)
        db.flush()
        unit.occupancy_status = OccupancyStatus.occupied.value
        added_rows.append((rm, unit))

    if prop.is_multi_unit:
        units_all = db.query(Unit).filter(Unit.property_id == property_id).all()
        occupied_count = sum(
            1 for u in units_all if (u.occupancy_status or "").lower() == OccupancyStatus.occupied.value
        )
        prop.occupancy_status = OccupancyStatus.occupied.value if occupied_count > 0 else OccupancyStatus.vacant.value
    else:
        prop.occupancy_status = OccupancyStatus.occupied.value

    mgr = db.query(User).filter(User.id == manager_user_id).first()
    mgr_email = (mgr.email or "").strip() if mgr else None
    prop_name = (prop.name or f"{prop.street}, {prop.city}").strip() or f"Property {property_id}"
    ip = request.client.host if request and request.client else None
    ua = (request.headers.get("user-agent") or "").strip() if request else None

    if added_rows:
        labels = [(u.unit_label or "").strip() or str(u.id) for _, u in added_rows]
        unit_labels_joined = ", ".join(labels)
        if initiator == "manager":
            msg = (
                f"Property manager {mgr_email or manager_user_id} registered as on-site resident for all units "
                f"({unit_labels_joined}) at {prop_name} (self-service; Personal Mode)."
            )
        else:
            msg = (
                f"Property manager {mgr_email or manager_user_id} added as on-site resident for all units "
                f"({unit_labels_joined}) at {prop_name} (Personal Mode)."
            )
        first_rm = added_rows[0][0]
        create_ledger_event(
            db,
            ACTION_MANAGER_ONSITE_RESIDENT_ADDED,
            target_object_type="ResidentMode",
            target_object_id=first_rm.id,
            property_id=property_id,
            unit_id=added_rows[0][1].id,
            actor_user_id=actor_user_id,
            meta={
                "message": msg,
                "manager_user_id": manager_user_id,
                "manager_email": mgr_email,
                "all_units_batch": True,
                "unit_ids_added": [u.id for _, u in added_rows],
                "unit_labels": labels,
                "initiated_by": initiator,
            },
            ip_address=ip,
            user_agent=ua,
        )

    db.commit()

    all_unit_ids = sorted(existing_unit_ids | {u.id for u in units})
    if not added_rows:
        extra = (
            f" {removed_other_manager_count} other manager(s) were removed from this property."
            if removed_other_manager_count
            else ""
        )
        return {
            "status": "success",
            "message": f"Manager already has Personal Mode for every unit at this property.{extra}",
            "unit_ids": all_unit_ids,
            "removed_other_managers": removed_other_manager_count,
        }

    extra_mgr = (
        f" {removed_other_manager_count} other manager(s) were removed from this property."
        if removed_other_manager_count
        else ""
    )
    return {
        "status": "success",
        "message": (
            "You are now registered as on-site resident for all units. Switch to Personal mode per unit as needed."
            if initiator == "manager"
            else f"Manager added as on-site resident for all units. They now have Personal Mode for each unit.{extra_mgr}"
        ),
        "unit_ids": all_unit_ids,
        "removed_other_managers": removed_other_manager_count,
    }


def add_manager_onsite_resident(
    db: Session,
    property_id: int,
    manager_user_id: int,
    unit_id: int | None,
    *,
    actor_user_id: int,
    initiator: str,
    request: Request | None,
    confirm_remove_other_managers: bool = False,
) -> dict:
    """
    Create ResidentMode for manager at unit. initiator: 'owner' | 'manager' (for ledger copy only).

    Owner + multi-unit property with exactly one unit: granting on-site access covers the whole
    building (same as all-units); other managers require confirm_remove_other_managers or 409.
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

    removed_other_manager_count = 0
    if initiator == "owner":
        units_all = db.query(Unit).filter(Unit.property_id == property_id).order_by(Unit.id).all()
        if len(units_all) == 1:
            other_assignments = (
                db.query(PropertyManagerAssignment)
                .filter(
                    PropertyManagerAssignment.property_id == property_id,
                    PropertyManagerAssignment.user_id != manager_user_id,
                )
                .count()
            )
            if other_assignments > 0:
                if not confirm_remove_other_managers:
                    raise HTTPException(
                        status_code=409,
                        detail=(
                            "OTHER_MANAGERS_PRESENT: Assigning on-site access for the only unit on this property "
                            "removes every other property manager. Resend the request with "
                            "confirm_remove_other_managers set to true to proceed."
                        ),
                    )
                removed_other_manager_count = remove_other_property_managers_from_property(
                    db,
                    property_id,
                    manager_user_id,
                    actor_user_id=actor_user_id,
                    request=request,
                    prop=prop,
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
    extra_mgr = (
        f" {removed_other_manager_count} other manager(s) were removed from this property."
        if removed_other_manager_count
        else ""
    )
    return {
        "status": "success",
        "message": (
            "You are now registered as on-site resident for this unit. Switch to Personal mode to set presence and use guest features for your unit."
            if initiator == "manager"
            else f"Manager added as on-site resident. They now have Personal Mode for this unit.{extra_mgr}"
        ),
        "unit_id": resolved_unit_id,
        "removed_other_managers": removed_other_manager_count,
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

    residents = (
        db.query(ResidentMode)
        .join(Unit, ResidentMode.unit_id == Unit.id)
        .filter(
            ResidentMode.user_id == manager_user_id,
            ResidentMode.mode == ResidentModeType.manager_personal,
            Unit.property_id == property_id,
        )
        .order_by(ResidentMode.unit_id)
        .all()
    )
    if not residents:
        raise HTTPException(status_code=404, detail="No on-site resident registration found for this property.")

    mgr = db.query(User).filter(User.id == manager_user_id).first()
    mgr_email = (mgr.email or "").strip() if mgr else None
    prop_name = (prop.name or f"{prop.street}, {prop.city}").strip() or f"Property {property_id}"
    ip = request.client.host if request and request.client else None
    ua = (request.headers.get("user-agent") or "").strip() if request else None

    unit_ids = sorted({r.unit_id for r in residents})
    label_parts: list[str] = []
    for uid in unit_ids:
        unit_row = db.query(Unit).filter(Unit.id == uid).first()
        label_parts.append((unit_row.unit_label or "").strip() if unit_row else str(uid))
    unit_labels_joined = ", ".join(label_parts)

    if len(residents) == 1:
        if initiator == "manager":
            msg = (
                f"Property manager {mgr_email or manager_user_id} removed their on-site resident registration for Unit {unit_labels_joined} "
                f"at {prop_name} (self-service; management assignment unchanged)."
            )
        else:
            msg = (
                f"Property manager {mgr_email or manager_user_id} removed as on-site resident for Unit {unit_labels_joined} "
                f"at {prop_name} (Personal Mode link removed; manager assignment unchanged)."
            )
    else:
        if initiator == "manager":
            msg = (
                f"Property manager {mgr_email or manager_user_id} removed their on-site resident registration for all units "
                f"({unit_labels_joined}) at {prop_name} (self-service; management assignment unchanged)."
            )
        else:
            msg = (
                f"Property manager {mgr_email or manager_user_id} removed as on-site resident for all units "
                f"({unit_labels_joined}) at {prop_name} (Personal Mode link removed; manager assignment unchanged)."
            )

    create_ledger_event(
        db,
        ACTION_MANAGER_ONSITE_RESIDENT_REMOVED,
        target_object_type="ResidentMode",
        target_object_id=residents[0].id,
        property_id=property_id,
        unit_id=unit_ids[0] if len(unit_ids) == 1 else None,
        actor_user_id=actor_user_id,
        meta={
            "message": msg,
            "manager_user_id": manager_user_id,
            "manager_email": mgr_email,
            "unit_ids": unit_ids,
            "unit_labels": label_parts,
            "all_units_removed": len(residents) > 1,
            "initiated_by": initiator,
        },
        ip_address=ip,
        user_agent=ua,
    )

    for resident in residents:
        db.delete(resident)

    for unit_id in unit_ids:
        unit = db.query(Unit).filter(Unit.id == unit_id).first()
        if not unit:
            continue
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
        uid0 = unit_ids[0]
        has_active_stay = (
            db.query(Stay)
            .filter(
                Stay.unit_id == uid0,
                Stay.checked_in_at.isnot(None),
                Stay.checked_out_at.is_(None),
                Stay.cancelled_at.is_(None),
            )
            .first()
        ) is not None
        prop.occupancy_status = OccupancyStatus.vacant.value if not has_active_stay else prop.occupancy_status

    db.commit()
    return {
        "status": "success",
        "message": "Your on-site resident registration was removed. You remain assigned as property manager."
        if initiator == "manager"
        else (
            "Manager removed as on-site resident. They remain assigned as manager; those units are now vacant where there is no active stay."
            if len(unit_ids) > 1
            else "Manager removed as on-site resident. They remain assigned as manager; the unit is now vacant (if no active stay)."
        ),
    }
