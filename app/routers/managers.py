"""Property Manager routes: assigned properties, units, occupancy, invite tenants, view logs (read-only billing)."""
import secrets
from datetime import date, datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Request, Body
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field
from app.database import get_db
from app.models.user import User
from app.models.owner import Property, OwnerProfile, OccupancyStatus
from app.models.unit import Unit
from app.models.property_manager_assignment import PropertyManagerAssignment
from app.models.invitation import Invitation
from app.services.occupancy import (
    count_effectively_occupied_units,
    get_property_display_occupancy_status,
    get_unit_display_occupancy_status,
    get_units_occupancy_display,
)
from app.models.guest import PurposeOfStay, RelationshipToOwner
from app.dependencies import get_current_user, require_property_manager, require_property_manager_identity_verified, get_context_mode
from app.services.permissions import can_view_audit_logs, get_manager_personal_mode_units, get_manager_personal_mode_property_ids
from app.services.manager_resident import add_manager_onsite_resident, remove_manager_onsite_resident
from app.services.jle import validate_stay_duration_for_property
from app.services.audit_log import create_log, CATEGORY_STATUS_CHANGE
from app.services.event_ledger import create_ledger_event, ACTION_TENANT_INVITED
from app.services.shield_mode_policy import effective_shield_mode_enabled
from app.models.audit_log import AuditLog

router = APIRouter(prefix="/managers", tags=["managers"])


class InviteTenantRequest(BaseModel):
    tenant_name: str
    tenant_email: str = Field(..., min_length=1, description="Tenant email (required)")
    lease_start_date: str
    lease_end_date: str


class MyResidentModeRequest(BaseModel):
    """Unit you occupy as on-site resident. Omit or use 0 for single-unit properties (one implicit unit)."""

    unit_id: int | None = None


class PropertySummary(BaseModel):
    id: int
    name: str | None
    address: str
    street: str | None = None
    city: str | None = None
    state: str | None = None
    zip_code: str | None = None
    occupancy_status: str
    unit_count: int
    occupied_count: int
    region_code: str | None = None
    property_type_label: str | None = None
    is_multi_unit: bool = False
    shield_mode_enabled: bool = False


class UnitSummary(BaseModel):
    id: int
    unit_label: str
    occupancy_status: str
    occupied_by: str | None = None  # guest name, "X (Property manager)", or tenant name
    invite_id: str | None = None  # invitation_code when applicable (not for manager/tenant)


@router.get("/properties", response_model=list[PropertySummary])
def list_assigned_properties(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_property_manager_identity_verified),
    context_mode: str = Depends(get_context_mode),
):
    """List properties. Business mode: assigned properties (management scope). Personal mode: only properties where manager lives (ResidentMode)."""
    assignments = (
        db.query(PropertyManagerAssignment)
        .filter(PropertyManagerAssignment.user_id == current_user.id)
        .all()
    )
    property_ids = list({a.property_id for a in assignments})
    if not property_ids:
        return []
    if context_mode == "personal":
        personal_unit_ids = get_manager_personal_mode_units(db, current_user.id)
        if not personal_unit_ids:
            return []
        units = db.query(Unit).filter(Unit.id.in_(personal_unit_ids)).all()
        personal_property_ids = {u.property_id for u in units}
        property_ids = [pid for pid in property_ids if pid in personal_property_ids]
        if not property_ids:
            return []
    props = (
        db.query(Property)
        .filter(Property.id.in_(property_ids), Property.deleted_at.is_(None))
        .all()
    )
    out = []
    for p in props:
        units = db.query(Unit).filter(Unit.property_id == p.id).all()
        unit_count = len(units) if units else 1  # single-unit: 1 implicit
        occupied = (
            count_effectively_occupied_units(db, units)
            if units
            else (1 if (p.occupancy_status or "").lower() == OccupancyStatus.occupied.value else 0)
        )
        prop_status = get_property_display_occupancy_status(db, p, units) if units else (p.occupancy_status or OccupancyStatus.unknown.value)
        if not units:
            prop_status = OccupancyStatus.occupied.value if occupied > 0 else (p.occupancy_status or OccupancyStatus.unknown.value)
        address = ", ".join(filter(None, [p.street, p.city, p.state, p.zip_code or ""]))
        out.append(
            PropertySummary(
                id=p.id,
                name=p.name,
                address=address,
                occupancy_status=prop_status,
                unit_count=unit_count,
                occupied_count=occupied,
                region_code=getattr(p, "region_code", None),
                shield_mode_enabled=effective_shield_mode_enabled(p),
            )
        )
    return out


@router.get("/properties/{property_id}", response_model=PropertySummary)
def get_property(
    property_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_property_manager_identity_verified),
    context_mode: str = Depends(get_context_mode),
):
    """Read-only property summary. Business: assigned properties only. Personal: only properties manager is assigned to live on."""
    if not db.query(PropertyManagerAssignment).filter(
        PropertyManagerAssignment.property_id == property_id,
        PropertyManagerAssignment.user_id == current_user.id,
    ).first():
        raise HTTPException(status_code=404, detail="Property not found or not assigned to you")
    if context_mode == "personal":
        personal_ids = get_manager_personal_mode_property_ids(db, current_user.id)
        if property_id not in personal_ids:
            raise HTTPException(status_code=404, detail="Property not found or you are not assigned to live on this property")
    prop = db.query(Property).filter(Property.id == property_id, Property.deleted_at.is_(None)).first()
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")
    units = db.query(Unit).filter(Unit.property_id == property_id).all()
    unit_count = len(units) if units else 1
    occupied = (
        count_effectively_occupied_units(db, units)
        if units
        else (1 if (prop.occupancy_status or "").lower() == OccupancyStatus.occupied.value else 0)
    )
    prop_status = (
        get_property_display_occupancy_status(db, prop, units)
        if units
        else (OccupancyStatus.occupied.value if occupied > 0 else (prop.occupancy_status or OccupancyStatus.unknown.value))
    )
    address = ", ".join(filter(None, [prop.street, prop.city, prop.state, prop.zip_code or ""]))
    return PropertySummary(
        id=prop.id,
        name=prop.name,
        address=address,
        street=prop.street,
        city=prop.city,
        state=prop.state,
        zip_code=prop.zip_code,
        occupancy_status=prop_status,
        unit_count=unit_count,
        occupied_count=occupied,
        region_code=getattr(prop, "region_code", None),
        property_type_label=getattr(prop, "property_type_label", None) or (prop.property_type.value if prop.property_type else None),
        is_multi_unit=getattr(prop, "is_multi_unit", False),
        shield_mode_enabled=effective_shield_mode_enabled(prop),
    )


@router.get("/properties/{property_id}/units", response_model=list[UnitSummary])
def list_property_units(
    property_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_property_manager_identity_verified),
    context_mode: str = Depends(get_context_mode),
):
    """List units for an assigned property. Business: assigned only. Personal: only if manager is assigned to live on this property."""
    if not db.query(PropertyManagerAssignment).filter(
        PropertyManagerAssignment.property_id == property_id,
        PropertyManagerAssignment.user_id == current_user.id,
    ).first():
        raise HTTPException(status_code=404, detail="Property not found or not assigned to you")
    if context_mode == "personal":
        personal_ids = get_manager_personal_mode_property_ids(db, current_user.id)
        if property_id not in personal_ids:
            raise HTTPException(status_code=404, detail="Property not found or you are not assigned to live on this property")
    prop = db.query(Property).filter(Property.id == property_id).first()
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")
    units = db.query(Unit).filter(Unit.property_id == property_id).all()
    if not units:
        # Single-unit property: return implicit unit
        return [
            UnitSummary(
                id=0,
                unit_label="1",
                occupancy_status=prop.occupancy_status or OccupancyStatus.unknown.value,
                occupied_by=None,
                invite_id=None,
            )
        ]
    unit_ids = [u.id for u in units]
    if context_mode == "personal":
        guest_detail_units = set(get_manager_personal_mode_units(db, current_user.id))
        occupancy_display = get_units_occupancy_display(
            db, unit_ids, anonymize_tenant_lane=False, guest_detail_unit_ids=guest_detail_units
        )
    else:
        occupancy_display = {}
    return [
        UnitSummary(
            id=u.id,
            unit_label=u.unit_label,
            occupancy_status=get_unit_display_occupancy_status(db, u),
            occupied_by=occupancy_display.get(u.id, {}).get("occupied_by") if context_mode == "personal" else None,
            invite_id=occupancy_display.get(u.id, {}).get("invite_id") if context_mode == "personal" else None,
        )
        for u in units
    ]


@router.post("/properties/{property_id}/my-resident-mode")
def register_my_resident_mode(
    property_id: int,
    data: MyResidentModeRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_property_manager_identity_verified),
):
    """Manager self-service: link this assigned property to Personal Mode for the unit you occupy (on-site resident)."""
    uid = data.unit_id if data.unit_id and data.unit_id > 0 else None
    return add_manager_onsite_resident(
        db,
        property_id,
        current_user.id,
        uid,
        actor_user_id=current_user.id,
        initiator="manager",
        request=request,
    )


@router.delete("/properties/{property_id}/my-resident-mode")
def remove_my_resident_mode(
    property_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_property_manager_identity_verified),
):
    """Manager removes their own on-site resident registration; property manager assignment is unchanged."""
    return remove_manager_onsite_resident(
        db,
        property_id,
        current_user.id,
        actor_user_id=current_user.id,
        initiator="manager",
        request=request,
    )


@router.post("/units/{unit_id}/invite-tenant")
def invite_tenant(
    unit_id: int,
    request: Request,
    data: InviteTenantRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_property_manager_identity_verified),
):
    """Create an invitation for a tenant to register. Manager must be assigned to the property."""
    unit = db.query(Unit).filter(Unit.id == unit_id).first()
    if not unit:
        raise HTTPException(status_code=404, detail="Unit not found")
    if not db.query(PropertyManagerAssignment).filter(
        PropertyManagerAssignment.property_id == unit.property_id,
        PropertyManagerAssignment.user_id == current_user.id,
    ).first():
        raise HTTPException(status_code=403, detail="You are not assigned to this property")
    prop = db.query(Property).filter(Property.id == unit.property_id).first()
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")
    owner_profile = db.query(OwnerProfile).filter(OwnerProfile.id == prop.owner_profile_id).first()
    owner_user_id = owner_profile.user_id if owner_profile else None
    if not owner_user_id:
        raise HTTPException(status_code=500, detail="Property has no owner")
    tenant_name = (data.tenant_name or "").strip()
    tenant_email = (data.tenant_email or "").strip()
    if not tenant_name:
        raise HTTPException(status_code=400, detail="tenant_name is required")
    if tenant_email:
        from app.services.permissions import validate_invite_email_role
        from app.models.user import UserRole
        role_err = validate_invite_email_role(db, tenant_email, UserRole.tenant)
        if role_err:
            raise HTTPException(status_code=409, detail=role_err)
    try:
        start = datetime.strptime(data.lease_start_date, "%Y-%m-%d").date()
        end = datetime.strptime(data.lease_end_date, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="lease_start_date and lease_end_date must be YYYY-MM-DD")
    if end <= start:
        raise HTTPException(status_code=400, detail="lease_end_date must be after lease_start_date")
    if start < date.today():
        raise HTTPException(status_code=400, detail="Lease start date cannot be in the past")
    region_code = getattr(prop, "region_code", None) or ""
    owner_occupied = bool(getattr(prop, "owner_occupied", False))
    jurisdiction_error = validate_stay_duration_for_property(db, region_code, owner_occupied, start, end)
    if jurisdiction_error:
        raise HTTPException(status_code=400, detail=jurisdiction_error)
    code = "INV-" + secrets.token_hex(4).upper()
    inv = Invitation(
        invitation_code=code,
        owner_id=owner_user_id,
        property_id=prop.id,
        unit_id=unit_id,
        invited_by_user_id=current_user.id,
        guest_name=tenant_name,
        guest_email=tenant_email or None,
        stay_start_date=start,
        stay_end_date=end,
        purpose_of_stay=PurposeOfStay.other,
        relationship_to_owner=RelationshipToOwner.other,
        region_code=prop.region_code,
        status="ongoing",
        token_state="BURNED",
        invitation_kind="tenant",
        dead_mans_switch_enabled=1,
        dead_mans_switch_alert_email=1,
        dead_mans_switch_alert_sms=0,
        dead_mans_switch_alert_dashboard=1,
        dead_mans_switch_alert_phone=0,
    )
    db.add(inv)
    db.commit()
    db.refresh(inv)
    ip = request.client.host if request.client else None
    ua = (request.headers.get("user-agent") or "").strip() or None
    create_log(
        db,
        CATEGORY_STATUS_CHANGE,
        "Invitation created (manager invite tenant)",
        f"Invite ID {code} created for tenant {tenant_name} at unit {unit_id}. Manager invited tenant to register.",
        property_id=prop.id,
        invitation_id=inv.id,
        actor_user_id=current_user.id,
        actor_email=current_user.email,
        ip_address=ip,
        user_agent=ua,
        meta={"invitation_code": code, "tenant_name": tenant_name, "tenant_email": tenant_email or "", "unit_id": unit_id},
    )
    tenant_invite_message = f"Tenant invitation created for {tenant_name} at Unit {getattr(unit, 'unit_label', unit_id)}. Invite ID {code}. Lease {start}–{end}."
    create_ledger_event(
        db,
        ACTION_TENANT_INVITED,
        target_object_type="Invitation",
        target_object_id=inv.id,
        property_id=prop.id,
        unit_id=unit_id,
        invitation_id=inv.id,
        actor_user_id=current_user.id,
        meta={
            "message": tenant_invite_message,
            "invitation_code": code,
            "tenant_name": tenant_name,
            "tenant_email": tenant_email or "",
            "unit_id": unit_id,
            "lease_start_date": str(start),
            "lease_end_date": str(end),
        },
        ip_address=ip,
        user_agent=ua,
    )
    db.commit()
    return {"invitation_code": code, "status": "success", "message": "Tenant invitation created. Share the invite link with the tenant."}
