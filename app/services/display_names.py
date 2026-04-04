"""
Resolve guest/tenant display names from profile, User, AgreementSignature, and invitations.

Avoids the generic placeholder 'Guest' when any real identifier (name, email, invite id) exists.
"""
from __future__ import annotations

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.agreement_signature import AgreementSignature
from app.models.guest import GuestProfile
from app.models.invitation import Invitation
from app.models.stay import Stay
from app.models.tenant_assignment import TenantAssignment
from app.models.user import User
from app.services.invitation_kinds import is_property_invited_tenant_signup_kind


def label_from_user_id(db: Session, user_id: int | None) -> str | None:
    """Legal name, full name, or email for a user; None if missing."""
    if not user_id:
        return None
    u = db.query(User).filter(User.id == user_id).first()
    if not u:
        return None
    gp = db.query(GuestProfile).filter(GuestProfile.user_id == user_id).first()
    legal = (gp.full_legal_name if gp else None) or ""
    if legal.strip():
        return legal.strip()
    fn = (u.full_name or "").strip()
    if fn:
        return fn
    em = (u.email or "").strip()
    return em or None


def label_from_invitation(db: Session, inv: Invitation) -> str:
    """Best public label for who an invitation is for (guest or tenant)."""
    direct = (inv.guest_name or inv.guest_email or "").strip()
    if direct:
        return direct
    sig = (
        db.query(AgreementSignature)
        .filter(AgreementSignature.invitation_code == inv.invitation_code)
        .order_by(AgreementSignature.signed_at.desc())
        .first()
    )
    if sig:
        s = (sig.guest_full_name or sig.guest_email or "").strip()
        if s:
            return s
    stay = db.query(Stay).filter(Stay.invitation_id == inv.id).first()
    if stay and stay.guest_id:
        ulabel = label_from_user_id(db, stay.guest_id)
        if ulabel:
            return ulabel
    inv_kind = (getattr(inv, "invitation_kind", None) or "").strip().lower()
    if is_property_invited_tenant_signup_kind(inv_kind) and inv.unit_id:
        email = (getattr(inv, "guest_email", None) or "").strip().lower()
        q = db.query(TenantAssignment).filter(TenantAssignment.unit_id == inv.unit_id)
        if email:
            q = q.join(User, User.id == TenantAssignment.user_id).filter(
                func.lower(func.trim(User.email)) == email
            )
        ta = q.order_by(TenantAssignment.created_at.desc()).first()
        if not ta:
            ta = (
                db.query(TenantAssignment)
                .filter(TenantAssignment.unit_id == inv.unit_id)
                .order_by(TenantAssignment.created_at.desc())
                .first()
            )
        if ta:
            ulabel = label_from_user_id(db, ta.user_id)
            if ulabel:
                return ulabel
    code = (inv.invitation_code or "").strip()
    if is_property_invited_tenant_signup_kind(inv_kind):
        return f"Tenant authorization {code}" if code else "Tenant authorization"
    return f"Authorization {code}" if code else "Unknown invitee"


def label_for_stay(db: Session, stay: Stay) -> str:
    """Display name for someone on a stay row."""
    if stay.guest_id:
        ulabel = label_from_user_id(db, stay.guest_id)
        if ulabel:
            return ulabel
    if stay.invitation_id:
        inv = db.query(Invitation).filter(Invitation.id == stay.invitation_id).first()
        if inv:
            return label_from_invitation(db, inv)
    return "Unknown invitee"


def label_for_tenant_assignee(db: Session, user_id: int | None) -> str:
    """Tenant/resident name or email."""
    if not user_id:
        return "Unknown resident"
    u = db.query(User).filter(User.id == user_id).first()
    if not u:
        return "Unknown resident"
    return ((u.full_name or "").strip() or (u.email or "").strip() or "Unknown resident")
