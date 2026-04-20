"""
Privacy lanes: data belongs to one of three lanes. Permissions follow the lane, not ownership.

KEY RULE: Ask "What lane does this data belong to?" — not "Who owns the property?"
Every record belongs to: property/management | tenant | guest. Permissions follow the lane.

1. Property/Management Lane: owner/manager-invited guests, property-level data
2. Tenant Lane: tenant-invited guests — private to the tenant, NEVER visible to owners/managers
3. Guest Lane: guest's own authorization, agreement, stay status

Ownership does NOT override privacy scope. Even if someone owns the property, switching to
personal mode does NOT unlock tenant-private information.
"""
from datetime import date

from sqlalchemy import or_
from sqlalchemy.orm import Session
from app.models.user import User, UserRole
from app.models.invitation import Invitation
from app.models.stay import Stay
from app.models.property_manager_assignment import PropertyManagerAssignment
from app.models.tenant_assignment import TenantAssignment
from app.services.event_ledger import (
    ACTION_AWAY_ACTIVATED,
    ACTION_AWAY_ENDED,
    ACTION_PRESENCE_STATUS_CHANGED,
)

# Unit resident presence (tenant/manager/owner); tenant-actor rows must not appear on owner/manager dashboards.
_TENANT_PRESENCE_LEDGER_ACTIONS = frozenset(
    {ACTION_AWAY_ACTIVATED, ACTION_AWAY_ENDED, ACTION_PRESENCE_STATUS_CHANGED}
)


def is_tenant_lane_invitation(db: Session, inv: Invitation) -> bool:
    """
    True if this invitation belongs to the tenant lane (created by a tenant).
    Tenant-invited guest data is private to the tenant — owners/managers must never see it.
    """
    inviter_id = getattr(inv, "invited_by_user_id", None)
    if inviter_id is None:
        return False  # Legacy: no inviter = treat as property lane
    inviter = db.query(User).filter(User.id == inviter_id).first()
    if not inviter:
        return False
    return inviter.role == UserRole.tenant


# Owner/manager dashboard: label when guest PII must not be shown (not the relationship owner).
REDACTED_GUEST_AUTHORIZATION_LABEL = "Guest authorization"


def relationship_owner_user_id_for_invitation(inv: Invitation) -> int | None:
    """User who created/owns the guest relationship for this invitation (inviter, else property owner record)."""
    uid = getattr(inv, "invited_by_user_id", None)
    if uid is not None:
        return uid
    return getattr(inv, "owner_id", None)


def relationship_owner_user_id_for_stay(db: Session, stay: Stay) -> int | None:
    """Relationship owner for a stay: stay.invited_by_user_id, else invitation inviter, else stay.owner_id."""
    uid = getattr(stay, "invited_by_user_id", None)
    if uid is not None:
        return uid
    inv_id = getattr(stay, "invitation_id", None)
    if inv_id is not None:
        inv = db.query(Invitation).filter(Invitation.id == inv_id).first()
        if inv:
            return relationship_owner_user_id_for_invitation(inv)
    return getattr(stay, "owner_id", None)


def viewer_is_relationship_owner_for_stay(db: Session, stay: Stay, viewer_user_id: int) -> bool:
    rel = relationship_owner_user_id_for_stay(db, stay)
    return rel is not None and rel == viewer_user_id


def viewer_is_relationship_owner_for_invitation(inv: Invitation, viewer_user_id: int) -> bool:
    rel = relationship_owner_user_id_for_invitation(inv)
    return rel is not None and rel == viewer_user_id


def is_tenant_lane_stay(db: Session, stay: Stay) -> bool:
    """True if this stay belongs to the tenant lane (guest was invited by a tenant)."""
    inv_id = getattr(stay, "invitation_id", None)
    if inv_id is None:
        inviter_id = getattr(stay, "invited_by_user_id", None)
        if inviter_id is None:
            return False
        inviter = db.query(User).filter(User.id == inviter_id).first()
        return inviter is not None and inviter.role == UserRole.tenant
    inv = db.query(Invitation).filter(Invitation.id == inv_id).first()
    return inv is not None and is_tenant_lane_invitation(db, inv)


def get_tenant_lane_invitation_ids(db: Session, invitation_ids: list[int]) -> set[int]:
    """Return the subset of invitation IDs that are tenant-lane."""
    if not invitation_ids:
        return set()
    invs = db.query(Invitation).filter(Invitation.id.in_(invitation_ids)).all()
    inviter_ids = list({getattr(i, "invited_by_user_id", None) for i in invs if getattr(i, "invited_by_user_id", None) is not None})
    if not inviter_ids:
        return set()
    tenant_ids = {u.id for u in db.query(User).filter(User.id.in_(inviter_ids), User.role == UserRole.tenant).all()}
    return {i.id for i in invs if getattr(i, "invited_by_user_id", None) in tenant_ids}


def get_tenant_lane_stay_ids(db: Session, stay_ids: list[int]) -> set[int]:
    """Return the subset of stay IDs that are tenant-lane."""
    if not stay_ids:
        return set()
    stays = db.query(Stay).filter(Stay.id.in_(stay_ids)).all()
    inv_ids = [s.invitation_id for s in stays if getattr(s, "invitation_id", None) is not None]
    tenant_inv_ids = get_tenant_lane_invitation_ids(db, inv_ids) if inv_ids else set()
    tenant_stay_ids = {s.id for s in stays if getattr(s, "invitation_id", None) in tenant_inv_ids}
    # Stays without invitation: check invited_by_user_id
    for s in stays:
        if s.id in tenant_stay_ids:
            continue
        if getattr(s, "invitation_id", None) is not None:
            continue
        inviter_id = getattr(s, "invited_by_user_id", None)
        if inviter_id is None:
            continue
        inviter = db.query(User).filter(User.id == inviter_id).first()
        if inviter and inviter.role == UserRole.tenant:
            tenant_stay_ids.add(s.id)
    return tenant_stay_ids


def is_property_lane_for_owner(db: Session, inv: Invitation, owner_user_id: int) -> bool:
    """
    True if this invitation is in the property/management lane for this owner.
    Owner can see: invitations they created, or that their assigned managers created.
    Owner cannot see: tenant-invited invitations.
    """
    if is_tenant_lane_invitation(db, inv):
        return False
    inviter_id = getattr(inv, "invited_by_user_id", None)
    if inviter_id == owner_user_id:
        return True
    if inviter_id is None:
        return inv.owner_id == owner_user_id
    inviter = db.query(User).filter(User.id == inviter_id).first()
    if not inviter:
        return False
    if inviter.role == UserRole.property_manager:
        return db.query(PropertyManagerAssignment).filter(
            PropertyManagerAssignment.property_id == inv.property_id,
            PropertyManagerAssignment.user_id == inviter_id,
        ).first() is not None
    return inviter.role == UserRole.owner and inv.owner_id == owner_user_id


def filter_property_lane_invitations_for_owner(db: Session, invitations: list[Invitation], owner_user_id: int) -> list[Invitation]:
    """Filter to only property-lane invitations (exclude tenant-invited)."""
    return [inv for inv in invitations if is_property_lane_for_owner(db, inv, owner_user_id)]


def filter_property_lane_stays_for_owner(db: Session, stays: list[Stay], owner_user_id: int) -> list[Stay]:
    """Filter to only property-lane stays (exclude tenant-invited guest stays)."""
    return [s for s in stays if not is_tenant_lane_stay(db, s)]


def filter_property_lane_invitations_for_manager(db: Session, invitations: list[Invitation], manager_user_id: int) -> list[Invitation]:
    """Manager sees only invitations they created (invited_by_user_id == manager)."""
    return [inv for inv in invitations if getattr(inv, "invited_by_user_id", None) == manager_user_id]


def filter_property_lane_stays_for_manager(db: Session, stays: list[Stay], manager_user_id: int) -> list[Stay]:
    """Manager sees only stays for guests they invited."""
    return [s for s in stays if getattr(s, "invited_by_user_id", None) == manager_user_id]


def filter_tenant_lane_from_ledger_rows(db: Session, rows: list) -> list:
    """
    Exclude EventLedger rows that reference tenant-lane invitations or stays.
    Use for owner logs and manager logs — owners/managers must never see tenant guest activity.
    """
    inv_ids = [getattr(r, "invitation_id", None) for r in rows if getattr(r, "invitation_id", None) is not None]
    stay_ids = [getattr(r, "stay_id", None) for r in rows if getattr(r, "stay_id", None) is not None]
    tenant_inv_ids = get_tenant_lane_invitation_ids(db, inv_ids) if inv_ids else set()
    tenant_stay_ids = get_tenant_lane_stay_ids(db, stay_ids) if stay_ids else set()
    return [
        r for r in rows
        if getattr(r, "invitation_id", None) not in tenant_inv_ids
        and getattr(r, "stay_id", None) not in tenant_stay_ids
    ]


def filter_tenant_presence_from_owner_manager_ledger(db: Session, rows: list) -> list:
    """
    Drop EventLedger rows for unit presence/away when the actor is a tenant.
    Owners and managers must not see tenant present/away status in notifications or the event ledger.
    """
    if not rows:
        return rows
    actor_ids = {
        r.actor_user_id
        for r in rows
        if getattr(r, "action_type", None) in _TENANT_PRESENCE_LEDGER_ACTIONS and r.actor_user_id
    }
    if not actor_ids:
        return rows
    tenant_actor_ids = {
        u.id
        for u in db.query(User).filter(User.id.in_(actor_ids), User.role == UserRole.tenant).all()
    }
    if not tenant_actor_ids:
        return rows
    return [
        r
        for r in rows
        if not (
            getattr(r, "action_type", None) in _TENANT_PRESENCE_LEDGER_ACTIONS
            and r.actor_user_id in tenant_actor_ids
        )
    ]


def filter_manager_presence_on_tenant_leased_units(db: Session, rows: list) -> list:
    """
    Property managers must not see unit-level resident presence/away (here/away) for units
    that have an active tenant lease — that activity is tenant-private. Guest-stay presence
    ledger rows (stay_id set) stay visible. Also drops owner/manager resident presence logged
    on the same unit as an active lease (avoids indirect tenant context).
    """
    if not rows:
        return rows
    today = date.today()
    candidates = [
        r
        for r in rows
        if getattr(r, "action_type", None) in _TENANT_PRESENCE_LEDGER_ACTIONS
        and getattr(r, "stay_id", None) is None
        and getattr(r, "unit_id", None) is not None
    ]
    if not candidates:
        return rows
    unit_ids = list({r.unit_id for r in candidates if r.unit_id is not None})
    if not unit_ids:
        return rows
    leased_unit_ids = {
        row[0]
        for row in db.query(TenantAssignment.unit_id)
        .filter(
            TenantAssignment.unit_id.in_(unit_ids),
            TenantAssignment.start_date <= today,
            or_(TenantAssignment.end_date.is_(None), TenantAssignment.end_date >= today),
        )
        .distinct()
        .all()
    }
    if not leased_unit_ids:
        return rows
    return [
        r
        for r in rows
        if not (
            getattr(r, "action_type", None) in _TENANT_PRESENCE_LEDGER_ACTIONS
            and getattr(r, "stay_id", None) is None
            and getattr(r, "unit_id", None) in leased_unit_ids
        )
    ]
