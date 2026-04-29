"""Guest-stay (property-lane) email recipients: only the inviter, and only for personal-mode hosting.

Without a stored API context_mode on invitations, \"personal\" matches dashboard rules: the invite/stay
must fall on the owner's primary-residence units (owner_personal_guest_scope) or a manager's on-site
resident units (manager_personal). Portfolio/business hosting does not email owners or other managers.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.invitation import Invitation
from app.models.stay import Stay
from app.models.user import User, UserRole
from app.services.permissions import (
    get_manager_personal_mode_units,
    invitation_in_manager_personal_guest_scope,
    invitation_in_owner_personal_guest_scope,
    owner_personal_guest_scope_unit_ids,
    stay_in_manager_personal_guest_scope,
    stay_in_owner_personal_guest_scope,
)
from app.services.privacy_lanes import (
    is_tenant_lane_stay,
    relationship_owner_user_id_for_invitation,
    relationship_owner_user_id_for_stay,
)


def _inviter_is_personal_guest_host_for_invitation(db: Session, inv: Invitation) -> bool:
    """True when the relationship inviter is an owner/manager hosting on their personal-scope unit."""
    rel_id = relationship_owner_user_id_for_invitation(inv)
    if rel_id is None:
        return False
    inviter = db.query(User).filter(User.id == rel_id).first()
    if not inviter or inviter.role == UserRole.tenant:
        return False
    if inviter.role == UserRole.owner:
        allowed = owner_personal_guest_scope_unit_ids(db, rel_id)
        return invitation_in_owner_personal_guest_scope(db, inv, allowed)
    if inviter.role == UserRole.property_manager:
        units = set(get_manager_personal_mode_units(db, rel_id))
        if not units:
            return False
        return invitation_in_manager_personal_guest_scope(db, inv, units)
    return False


def inviter_is_personal_guest_host_for_stay(db: Session, stay: Stay) -> bool:
    """Property-lane guest stays only; tenant-lane never uses portfolio owner/manager guest-stay mail."""
    if is_tenant_lane_stay(db, stay):
        return False
    inv_id = getattr(stay, "invitation_id", None)
    if inv_id is not None:
        inv = db.query(Invitation).filter(Invitation.id == inv_id).first()
        if inv is not None:
            return _inviter_is_personal_guest_host_for_invitation(db, inv)
    # Legacy stay without invitation: treat as eligible only if invited_by is owner/manager on personal scope (rare)
    rel_id = relationship_owner_user_id_for_stay(db, stay)
    if rel_id is None:
        return False
    inviter = db.query(User).filter(User.id == rel_id).first()
    if not inviter or inviter.role not in (UserRole.owner, UserRole.property_manager):
        return False
    if inviter.role == UserRole.owner:
        allowed = owner_personal_guest_scope_unit_ids(db, rel_id)
        return stay_in_owner_personal_guest_scope(db, stay, allowed)
    units = set(get_manager_personal_mode_units(db, rel_id))
    if not units:
        return False
    return stay_in_manager_personal_guest_scope(db, stay, units)


def guest_stay_inviter_user_for_email(db: Session, stay: Stay) -> User | None:
    """User who may receive guest-stay owner-facing emails, or None if not inviter-on-personal-hosting."""
    if not inviter_is_personal_guest_host_for_stay(db, stay):
        return None
    rel_id = relationship_owner_user_id_for_stay(db, stay)
    if rel_id is None:
        return None
    return db.query(User).filter(User.id == rel_id).first()


def guest_invite_inviter_user_for_email(db: Session, inv: Invitation) -> User | None:
    """Inviter who may receive guest-invite lifecycle mail (DMS scheduled, etc.), or None."""
    if not _inviter_is_personal_guest_host_for_invitation(db, inv):
        return None
    rel_id = relationship_owner_user_id_for_invitation(inv)
    if rel_id is None:
        return None
    return db.query(User).filter(User.id == rel_id).first()


def owner_email_and_manager_emails_for_guest_invite_dms(db: Session, inv: Invitation) -> tuple[str, list[str]]:
    """DMS scheduled email: only the inviter when they are hosting on a personal-scope unit."""
    host = guest_invite_inviter_user_for_email(db, inv)
    if not host or not (host.email or "").strip():
        return "", []
    em = (host.email or "").strip()
    if host.role == UserRole.property_manager:
        return "", [em]
    return em, []


def owner_email_and_manager_emails_for_guest_stay_dms(db: Session, stay: Stay) -> tuple[str, list[str]]:
    """For guest-checkout DMS-off: same routing as PM-or-owner helper — only the personal-host inviter."""
    host = guest_stay_inviter_user_for_email(db, stay)
    if not host or not (host.email or "").strip():
        return "", []
    em = (host.email or "").strip()
    if host.role == UserRole.property_manager:
        return "", [em]
    return em, []
