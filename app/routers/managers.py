"""Property Manager routes: assigned properties, units, occupancy, invite tenants, view logs (read-only billing)."""
import secrets
from datetime import date, datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Request, Body
from sqlalchemy.orm import Session
from sqlalchemy import or_, func
from pydantic import BaseModel, Field
from app.database import get_db
from app.utils.client_calendar import effective_today_for_invite_start
from app.models.user import User
from app.models.owner import Property, OwnerProfile, OccupancyStatus
from app.models.unit import Unit
from app.models.property_manager_assignment import PropertyManagerAssignment
from app.models.invitation import Invitation
from app.models.tenant_assignment import TenantAssignment
from app.services.occupancy import (
    count_effectively_occupied_units,
    get_property_display_occupancy_status,
    get_unit_display_occupancy_status,
    get_units_occupancy_display,
    normalize_occupancy_status_for_display,
)
from app.models.guest import PurposeOfStay, RelationshipToOwner
from app.dependencies import get_current_user, require_property_manager, require_property_manager_identity_verified, get_context_mode
from app.services.permissions import can_view_audit_logs, get_manager_personal_mode_units, get_manager_personal_mode_property_ids
from app.services.manager_resident import add_manager_onsite_resident, remove_manager_onsite_resident
from app.services.jle import validate_stay_duration_for_property
from app.services.audit_log import create_log, CATEGORY_STATUS_CHANGE
from app.services.event_ledger import create_ledger_event, ACTION_TENANT_INVITED
from app.services.invitation_kinds import TENANT_COTENANT_INVITE_KIND, TENANT_INVITE_KIND, TENANT_UNIT_LEASE_KINDS
from app.services.tenant_lease_window import assert_unit_available_for_new_tenant_invite_or_raise
from app.services.shield_mode_policy import effective_shield_mode_enabled
from app.models.audit_log import AuditLog

router = APIRouter(prefix="/managers", tags=["managers"])


class InviteTenantRequest(BaseModel):
    tenant_name: str
    tenant_email: str = Field(..., min_length=1, description="Tenant email (required)")
    lease_start_date: str
    lease_end_date: str
    client_calendar_date: str | None = Field(
        None,
        description="Browser local calendar date YYYY-MM-DD; preferred when X-Client-Calendar-Date is stripped by proxies",
    )
    shared_lease: bool = Field(
        False,
        description="Additional occupant / shared lease: skips one-tenant-per-unit overlap checks for this invite only.",
    )


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
    # Public live slug; signed Master POA PDF: GET /public/live/{live_slug}/poa when on file.
    live_slug: str | None = None
    deleted_at: datetime | None = None


class UnitSummary(BaseModel):
    id: int
    unit_label: str
    occupancy_status: str
    occupied_by: str | None = None  # guest name, "X (Property manager)", or tenant name
    invite_id: str | None = None  # invitation_code when applicable (not for manager/tenant)
    current_tenant_name: str | None = None
    current_tenant_email: str | None = None
    lease_start_date: str | None = None  # YYYY-MM-DD
    lease_end_date: str | None = None  # YYYY-MM-DD; null on API means open-ended lease
    lease_cohort_member_count: int | None = None  # >1 when co-tenants share overlapping lease on this unit


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
    props = db.query(Property).filter(Property.id.in_(property_ids)).all()
    out = []
    for p in props:
        units = db.query(Unit).filter(Unit.property_id == p.id).all()
        unit_count = len(units) if units else 1  # single-unit: 1 implicit
        occupied = (
            count_effectively_occupied_units(db, units)
            if units
            else (1 if (p.occupancy_status or "").lower() == OccupancyStatus.occupied.value else 0)
        )
        if units:
            prop_status = get_property_display_occupancy_status(db, p, units)
        else:
            prop_status = (
                OccupancyStatus.occupied.value
                if occupied > 0
                else normalize_occupancy_status_for_display(
                    db, p.id, None, p.occupancy_status or OccupancyStatus.vacant.value
                )
            )
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
                live_slug=(getattr(p, "live_slug", None) or "").strip() or None,
                deleted_at=getattr(p, "deleted_at", None),
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
    prop = db.query(Property).filter(Property.id == property_id).first()
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
        else (
            OccupancyStatus.occupied.value
            if occupied > 0
            else normalize_occupancy_status_for_display(
                db, prop.id, None, prop.occupancy_status or OccupancyStatus.vacant.value
            )
        )
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
        live_slug=(getattr(prop, "live_slug", None) or "").strip() or None,
        deleted_at=getattr(prop, "deleted_at", None),
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
        # Single-unit property: return implicit unit; tenant invite may have unit_id=null
        today_su = date.today()
        inv_su = (
            db.query(Invitation)
            .filter(
                Invitation.property_id == property_id,
                Invitation.unit_id.is_(None),
                Invitation.invitation_kind.in_(tuple(TENANT_UNIT_LEASE_KINDS)),
                Invitation.token_state.notin_(["REVOKED", "CANCELLED", "EXPIRED"]),
            )
            .order_by(Invitation.created_at.desc())
            .first()
        )
        tn_su = te_su = tls_su = tle_su = None
        if inv_su:
            raw_n = (inv_su.guest_name or "").strip() or None
            te_su = (inv_su.guest_email or "").strip() or None
            tn_su = raw_n or te_su
            tls_su = inv_su.stay_start_date.isoformat() if inv_su.stay_start_date else None
            tle_su = inv_su.stay_end_date.isoformat() if inv_su.stay_end_date else None
        else:
            ta_su = (
                db.query(TenantAssignment)
                .join(Unit, TenantAssignment.unit_id == Unit.id)
                .filter(
                    Unit.property_id == property_id,
                    TenantAssignment.start_date <= today_su,
                    or_(TenantAssignment.end_date.is_(None), TenantAssignment.end_date >= today_su),
                )
                .order_by(TenantAssignment.created_at.desc())
                .first()
            )
            if ta_su:
                usr = db.query(User).filter(User.id == ta_su.user_id).first()
                te_su = ((usr.email or "").strip() or None) if usr else None
                tn_su = ((usr.full_name or "").strip() or te_su or None) if usr else None
                tls_su = ta_su.start_date.isoformat() if ta_su.start_date else None
                tle_su = ta_su.end_date.isoformat() if ta_su.end_date else None
        return [
            UnitSummary(
                id=0,
                unit_label="1",
                occupancy_status=normalize_occupancy_status_for_display(
                    db, prop.id, None, prop.occupancy_status or OccupancyStatus.vacant.value
                ),
                occupied_by=None,
                invite_id=None,
                current_tenant_name=tn_su,
                current_tenant_email=te_su,
                lease_start_date=tls_su,
                lease_end_date=tle_su,
            )
        ]
    unit_ids = [u.id for u in units]
    if context_mode == "personal":
        guest_detail_units = set(get_manager_personal_mode_units(db, current_user.id))
        occupancy_display = get_units_occupancy_display(
            db,
            unit_ids,
            anonymize_tenant_lane=False,
            guest_detail_unit_ids=guest_detail_units,
            relationship_viewer_id=current_user.id,
        )
    else:
        occupancy_display = {}

    today = date.today()

    def _tuple_from_tenant_assignment(ta: TenantAssignment) -> tuple[str | None, str | None, str | None, str | None]:
        usr = db.query(User).filter(User.id == ta.user_id).first()
        email = ((usr.email or "").strip() or None) if usr else None
        name = ((usr.full_name or "").strip() or email or None) if usr else None
        ls = ta.start_date.isoformat() if ta.start_date else None
        le = ta.end_date.isoformat() if ta.end_date else None
        return name, email, ls, le

    def tenant_lease_display_for_unit(
        unit_id: int,
    ) -> tuple[str | None, str | None, str | None, str | None, int | None]:
        """
        Prefer an in-window TenantAssignment, then a future assignment, then a tenant Invitation on the unit
        (CSV / pending signup often have invitation + unit occupancy but no assignment row yet).
        """
        tas_active = (
            db.query(TenantAssignment)
            .filter(
                TenantAssignment.unit_id == unit_id,
                TenantAssignment.start_date <= today,
                or_(TenantAssignment.end_date.is_(None), TenantAssignment.end_date >= today),
            )
            .order_by(TenantAssignment.created_at.desc())
            .all()
        )
        if tas_active:
            from app.services.tenant_lease_cohort import cluster_assignments_for_unit

            clusters = cluster_assignments_for_unit(unit_id, tas_active)
            names: list[str] = []
            emails: list[str | None] = []
            starts: list[date] = []
            ends: list[date | None] = []
            max_cohort = 1
            for cluster in clusters:
                max_cohort = max(max_cohort, len(cluster))
                for ta in sorted(cluster, key=lambda t: (t.user_id or 0, t.id)):
                    n, e, ls, le = _tuple_from_tenant_assignment(ta)
                    if n:
                        names.append(n)
                    if e:
                        emails.append(e)
                    if ta.start_date:
                        starts.append(ta.start_date)
                    ends.append(ta.end_date)
            display_name = " · ".join(names) if names else None
            email_out = emails[0] if emails else None
            ls_out = min(starts).isoformat() if starts else None
            if not ends:
                le_out = None
            else:
                finite = [x for x in ends if x is not None]
                if len(finite) != len(ends):
                    le_out = None
                else:
                    le_out = max(finite).isoformat()
            return display_name, email_out, ls_out, le_out, max_cohort if max_cohort > 1 else None

        ta_future = (
            db.query(TenantAssignment)
            .filter(
                TenantAssignment.unit_id == unit_id,
                TenantAssignment.start_date > today,
                or_(TenantAssignment.end_date.is_(None), TenantAssignment.end_date >= today),
            )
            .order_by(TenantAssignment.start_date.asc())
            .first()
        )
        if ta_future:
            fn, fe, fls, fle = _tuple_from_tenant_assignment(ta_future)
            return fn, fe, fls, fle, None

        inv = (
            db.query(Invitation)
            .filter(
                Invitation.unit_id == unit_id,
                Invitation.invitation_kind.in_(tuple(TENANT_UNIT_LEASE_KINDS)),
                Invitation.token_state.notin_(["REVOKED", "CANCELLED", "EXPIRED"]),
            )
            .order_by(Invitation.created_at.desc())
            .first()
        )
        if inv:
            raw_name = (inv.guest_name or "").strip() or None
            email = (inv.guest_email or "").strip() or None
            display_name = raw_name or email
            ls = inv.stay_start_date.isoformat() if inv.stay_start_date else None
            le = inv.stay_end_date.isoformat() if inv.stay_end_date else None
            return display_name, email, ls, le, None

        return None, None, None, None, None

    summaries: list[UnitSummary] = []
    for u in units:
        tn, te, tls, tle, tcohort = tenant_lease_display_for_unit(u.id)
        summaries.append(
            UnitSummary(
                id=u.id,
                unit_label=u.unit_label,
                occupancy_status=get_unit_display_occupancy_status(db, u),
                occupied_by=occupancy_display.get(u.id, {}).get("occupied_by") if context_mode == "personal" else None,
                invite_id=occupancy_display.get(u.id, {}).get("invite_id") if context_mode == "personal" else None,
                current_tenant_name=tn,
                current_tenant_email=te,
                lease_start_date=tls,
                lease_end_date=tle,
                lease_cohort_member_count=tcohort,
            )
        )
    return summaries


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
    if start < effective_today_for_invite_start(request, client_calendar_date=data.client_calendar_date):
        raise HTTPException(status_code=400, detail="Lease start date cannot be in the past")
    region_code = getattr(prop, "region_code", None) or ""
    owner_occupied = bool(getattr(prop, "owner_occupied", False))
    jurisdiction_error = validate_stay_duration_for_property(db, region_code, owner_occupied, start, end)
    if jurisdiction_error:
        raise HTTPException(status_code=400, detail=jurisdiction_error)
    assert_unit_available_for_new_tenant_invite_or_raise(db, unit_id, start, end, skip_overlap_check=data.shared_lease)
    inv_kind = TENANT_COTENANT_INVITE_KIND if data.shared_lease else TENANT_INVITE_KIND
    code = "INV-" + secrets.token_hex(4).upper()
    from app.models.demo_account import is_demo_user_id
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
        status="accepted",
        token_state="BURNED",
        invitation_kind=inv_kind,
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
    tenant_invite_message = f"Tenant invitation created for {tenant_name} at Unit {getattr(unit, 'unit_label', unit_id)}. Invite ID {code}. Lease {start}–{end}."
    create_log(
        db,
        CATEGORY_STATUS_CHANGE,
        "Invitation created",
        tenant_invite_message,
        property_id=prop.id,
        invitation_id=inv.id,
        actor_user_id=current_user.id,
        actor_email=current_user.email,
        ip_address=ip,
        user_agent=ua,
        meta={"invitation_code": code, "tenant_name": tenant_name, "tenant_email": tenant_email or "", "unit_id": unit_id},
    )
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
