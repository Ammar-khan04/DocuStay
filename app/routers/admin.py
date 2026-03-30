"""Admin API: users, audit logs, properties, stays. All routes require role=admin."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import or_, desc, cast, String

from app.database import get_db
from app.dependencies import require_admin
from app.models.user import User
from app.models.owner import Property, OwnerProfile
from app.models.audit_log import AuditLog
from app.models.event_ledger import EventLedger
from app.models.stay import Stay
from app.models.invitation import Invitation
from app.schemas.admin import (
    AdminUserView,
    AdminAuditLogEntry,
    AdminPropertyView,
    AdminStayView,
    AdminInvitationView,
)

router = APIRouter(prefix="/admin", tags=["admin"])


def _parse_optional_utc(s: str | None) -> datetime | None:
    if not s or not s.strip():
        return None
    try:
        d = datetime.fromisoformat(s.strip().replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d
    except (ValueError, TypeError):
        return None


@router.get("/users", response_model=list[AdminUserView])
def admin_list_users(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
    search: str | None = Query(None, description="Search by email or full_name"),
    role: str | None = Query(None, description="Filter by role: owner, guest, admin"),
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """List all users with optional search and role filter. Read-only."""
    q = db.query(User)
    if search and search.strip():
        term = f"%{search.strip()}%"
        q = q.filter(
            or_(User.email.ilike(term), (User.full_name or "").ilike(term))
        )
    if role and role.strip().lower() in ("owner", "guest", "admin"):
        q = q.filter(User.role == role.strip().lower())
    q = q.order_by(User.created_at.desc()).offset(offset).limit(limit)
    rows = q.all()
    return [
        AdminUserView(
            id=u.id,
            email=u.email,
            role=u.role.value,
            full_name=u.full_name,
            created_at=getattr(u, "created_at", None),
        )
        for u in rows
    ]


@router.get("/audit-logs", response_model=list[AdminAuditLogEntry])
def admin_list_audit_logs(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
    from_ts: str | None = Query(None, description="ISO UTC datetime"),
    to_ts: str | None = Query(None, description="ISO UTC datetime"),
    category: str | None = Query(None),
    property_id: int | None = Query(None),
    actor_user_id: int | None = Query(None),
    search: str | None = Query(None, description="Search in title/message"),
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """Global event ledger viewer with filters. No scoping to a single owner."""
    from app.services.event_ledger import ledger_event_to_display, get_actor_email, _CATEGORY_TO_ACTION_TYPES, ACTION_PROPERTY_DELETED

    q = db.query(EventLedger)
    from_dt = _parse_optional_utc(from_ts)
    to_dt = _parse_optional_utc(to_ts)
    if from_dt is not None:
        q = q.filter(EventLedger.created_at >= from_dt)
    if to_dt is not None:
        q = q.filter(EventLedger.created_at <= to_dt)
    if category and category.strip():
        action_types = _CATEGORY_TO_ACTION_TYPES.get(category.strip(), [])
        if action_types:
            q = q.filter(EventLedger.action_type.in_(action_types))
    if property_id is not None:
        q = q.filter(EventLedger.property_id == property_id)
    if actor_user_id is not None:
        q = q.filter(EventLedger.actor_user_id == actor_user_id)
    if search and search.strip():
        term = f"%{search.strip()}%"
        q = q.filter(
            (EventLedger.action_type.ilike(term)) | (cast(EventLedger.meta, String).ilike(term))
        )
    q = q.order_by(desc(EventLedger.created_at)).offset(offset).limit(limit)
    rows = q.all()
    prop_ids = {r.property_id for r in rows if r.property_id}
    props = {p.id: p.name or f"{p.city}, {p.state}" for p in db.query(Property).filter(Property.id.in_(prop_ids)).all()} if prop_ids else {}

    def _property_name(r):
        if r.property_id:
            return props.get(r.property_id)
        if r.action_type == ACTION_PROPERTY_DELETED and r.meta and isinstance(r.meta, dict):
            return r.meta.get("property_name")
        return None

    out = []
    for r in rows:
        cat, title, msg = ledger_event_to_display(r)
        actor_email = get_actor_email(db, r.actor_user_id)
        out.append(
            AdminAuditLogEntry(
                id=r.id,
                property_id=r.property_id,
                stay_id=r.stay_id,
                invitation_id=r.invitation_id,
                category=cat,
                title=title,
                message=msg,
                actor_user_id=r.actor_user_id,
                actor_email=actor_email,
                ip_address=r.ip_address,
                created_at=r.created_at or datetime.now(timezone.utc),
                property_name=_property_name(r),
            )
        )
    return out


@router.get("/properties", response_model=list[AdminPropertyView])
def admin_list_properties(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
    search: str | None = Query(None, description="Search name, street, city, state"),
    region_code: str | None = Query(None),
    state: str | None = Query(None, description="Filter by property state (e.g. CA, NY)"),
    include_deleted: bool = Query(False, description="Include soft-deleted properties"),
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """List all properties with optional search. Read-only."""
    q = db.query(Property)
    if not include_deleted:
        q = q.filter(Property.deleted_at.is_(None))
    if search and search.strip():
        term = f"%{search.strip()}%"
        q = q.filter(
            or_(
                (Property.name or "").ilike(term),
                (Property.street or "").ilike(term),
                (Property.city or "").ilike(term),
                (Property.state or "").ilike(term),
            )
        )
    if region_code and region_code.strip():
        q = q.filter(Property.region_code == region_code.strip().upper())
    if state and state.strip():
        q = q.filter(Property.state.ilike(state.strip()))
    q = q.order_by(Property.created_at.desc()).offset(offset).limit(limit)
    rows = q.all()
    owner_ids = {p.owner_profile_id for p in rows}
    profiles = {}
    if owner_ids:
        for pr in db.query(OwnerProfile).filter(OwnerProfile.id.in_(owner_ids)).all():
            u = db.query(User).filter(User.id == pr.user_id).first()
            profiles[pr.id] = u.email if u else None
    return [
        AdminPropertyView(
            id=p.id,
            owner_profile_id=p.owner_profile_id,
            owner_email=profiles.get(p.owner_profile_id),
            name=p.name,
            street=p.street,
            city=p.city,
            state=p.state,
            zip_code=p.zip_code,
            region_code=p.region_code,
            occupancy_status=getattr(p, "occupancy_status", None),
            deleted_at=getattr(p, "deleted_at", None),
            created_at=getattr(p, "created_at", None),
        )
        for p in rows
    ]


@router.get("/stays", response_model=list[AdminStayView])
def admin_list_stays(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
    property_id: int | None = Query(None),
    owner_id: int | None = Query(None),
    guest_id: int | None = Query(None),
    state: str | None = Query(None, description="Filter by property state (e.g. CA, NY)"),
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """List all stays with optional filters. Read-only."""
    q = db.query(Stay)
    if property_id is not None:
        q = q.filter(Stay.property_id == property_id)
    if owner_id is not None:
        q = q.filter(Stay.owner_id == owner_id)
    if guest_id is not None:
        q = q.filter(Stay.guest_id == guest_id)
    if state and state.strip():
        q = q.join(Property, Stay.property_id == Property.id).filter(Property.state.ilike(state.strip()))
    q = q.order_by(Stay.created_at.desc()).offset(offset).limit(limit)
    rows = q.all()
    user_ids = set()
    prop_ids = set()
    for s in rows:
        user_ids.add(s.guest_id)
        user_ids.add(s.owner_id)
        prop_ids.add(s.property_id)
    users = {}
    if user_ids:
        for u in db.query(User).filter(User.id.in_(user_ids)).all():
            users[u.id] = u.email
    props = {}
    if prop_ids:
        for p in db.query(Property).filter(Property.id.in_(prop_ids)).all():
            props[p.id] = p.name or f"{p.city}, {p.state}"
    return [
        AdminStayView(
            id=s.id,
            property_id=s.property_id,
            guest_id=s.guest_id,
            owner_id=s.owner_id,
            guest_email=users.get(s.guest_id),
            owner_email=users.get(s.owner_id),
            property_name=props.get(s.property_id),
            stay_start_date=s.stay_start_date,
            stay_end_date=s.stay_end_date,
            region_code=s.region_code,
            checked_in_at=s.checked_in_at,
            checked_out_at=s.checked_out_at,
            cancelled_at=s.cancelled_at,
            revoked_at=s.revoked_at,
            created_at=getattr(s, "created_at", None),
        )
        for s in rows
    ]


@router.get("/filters/states", response_model=list[str])
def admin_list_states(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Return distinct property state values (for filter dropdowns). Sorted ascending."""
    rows = (
        db.query(Property.state)
        .filter(Property.state.isnot(None), Property.state != "")
        .distinct()
        .order_by(Property.state)
        .all()
    )
    return [r[0] for r in rows if r[0]]


@router.get("/invitations", response_model=list[AdminInvitationView])
def admin_list_invitations(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
    property_id: int | None = Query(None),
    owner_id: int | None = Query(None),
    status: str | None = Query(None),
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """List all invitations with optional filters. Read-only."""
    q = db.query(Invitation)
    if property_id is not None:
        q = q.filter(Invitation.property_id == property_id)
    if owner_id is not None:
        q = q.filter(Invitation.owner_id == owner_id)
    if status and status.strip():
        q = q.filter(Invitation.status == status.strip())
    q = q.order_by(Invitation.created_at.desc()).offset(offset).limit(limit)
    rows = q.all()
    owner_ids = {inv.owner_id for inv in rows}
    prop_ids = {inv.property_id for inv in rows}
    users = {}
    if owner_ids:
        for u in db.query(User).filter(User.id.in_(owner_ids)).all():
            users[u.id] = u.email
    props = {}
    if prop_ids:
        for p in db.query(Property).filter(Property.id.in_(prop_ids)).all():
            props[p.id] = p.name or f"{p.city}, {p.state}"
    return [
        AdminInvitationView(
            id=inv.id,
            invitation_code=inv.invitation_code,
            owner_id=inv.owner_id,
            property_id=inv.property_id,
            owner_email=users.get(inv.owner_id),
            property_name=props.get(inv.property_id),
            guest_name=inv.guest_name,
            guest_email=inv.guest_email,
            stay_start_date=inv.stay_start_date,
            stay_end_date=inv.stay_end_date,
            status=inv.status or "pending",
            token_state=getattr(inv, "token_state", "STAGED"),
            created_at=getattr(inv, "created_at", None),
        )
        for inv in rows
    ]
