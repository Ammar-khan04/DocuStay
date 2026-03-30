"""Enforce one email address = one account type (UserRole) for new signups.

Existing DB rows may still have the same email under multiple roles (legacy uq_users_email_role);
new registrations are rejected at the API when the email is already used for a different role
or has an in-progress pending registration for a different role.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.pending_registration import PendingRegistration
from app.models.user import User, UserRole


def normalize_registration_email(email: str | None) -> str:
    return (email or "").strip().lower()


def users_with_normalized_email(db: Session, email_norm: str) -> list[User]:
    if not email_norm:
        return []
    return (
        db.query(User)
        .filter(func.lower(func.trim(User.email)) == email_norm)
        .all()
    )


def pending_registrations_with_normalized_email(db: Session, email_norm: str) -> list[PendingRegistration]:
    if not email_norm:
        return []
    return (
        db.query(PendingRegistration)
        .filter(func.lower(func.trim(PendingRegistration.email)) == email_norm)
        .all()
    )


def _role_labels(role: UserRole) -> tuple[str, str]:
    """(account type phrase, login page name)."""
    mapping: dict[UserRole, tuple[str, str]] = {
        UserRole.owner: ("property owner", "Owner"),
        UserRole.property_manager: ("property manager", "Property Manager"),
        UserRole.tenant: ("tenant", "Tenant"),
        UserRole.guest: ("guest", "Guest"),
        UserRole.admin: ("administrator", "Admin"),
    }
    return mapping.get(role, ("user", "correct"))


def email_registered_other_role_message(existing_role: UserRole, attempting_role: UserRole) -> str:
    """User-visible error when an account already exists under this email for another role."""
    ex_label, ex_page = _role_labels(existing_role)
    att_label, _ = _role_labels(attempting_role)
    return (
        f"This email is already registered as a {ex_label}. "
        f"Each email can only be used for one account type on DocuStay. "
        f"Sign in using the {ex_page} login page, or use a different email if you need to register as a {att_label}."
    )


def pending_other_role_message(pending_role: UserRole, attempting_role: UserRole) -> str:
    """Another signup flow is in progress for this email."""
    pend_label, _ = _role_labels(pending_role)
    att_label, _ = _role_labels(attempting_role)
    return (
        f"A registration is already in progress for this email as a {pend_label}. "
        f"Complete email verification for that signup, wait until the code expires, or use a different email. "
        f"You cannot start a {att_label} registration with the same email at the same time."
    )


def enforce_email_available_for_intended_role(
    db: Session,
    email_norm: str,
    intended_role: UserRole,
    *,
    allow_same_role_pending: bool = True,
) -> None:
    """
    Raise HTTPException 400 if email is taken by another role or has a non-expired pending registration
    for another role.

    If allow_same_role_pending is True, pending rows with the same role are ignored (callers may replace them).
    """
    if not email_norm:
        return
    for u in users_with_normalized_email(db, email_norm):
        if u.role != intended_role:
            raise HTTPException(
                status_code=400,
                detail=email_registered_other_role_message(u.role, intended_role),
            )
    now = datetime.now(timezone.utc)
    for p in pending_registrations_with_normalized_email(db, email_norm):
        if p.role == intended_role and allow_same_role_pending:
            continue
        if p.role != intended_role and p.expires_at >= now:
            raise HTTPException(
                status_code=400,
                detail=pending_other_role_message(p.role, intended_role),
            )


def same_role_already_registered_message(existing_role: UserRole) -> str:
    """Existing account with this email and role — tell them to log in."""
    ex_label, ex_page = _role_labels(existing_role)
    return (
        f"This email is already registered as a {ex_label}. "
        f"Please log in using the {ex_page} login page."
    )


def enforce_no_conflicting_user_before_pending_completion(db: Session, email_norm: str, pending_role: UserRole) -> None:
    """Before creating a User from PendingRegistration: email must not already have a user row."""
    for u in users_with_normalized_email(db, email_norm):
        if u.role != pending_role:
            raise HTTPException(
                status_code=400,
                detail=email_registered_other_role_message(u.role, pending_role),
            )
        raise HTTPException(
            status_code=400,
            detail=f"This email is already registered as a {_role_labels(pending_role)[0]}. Please log in instead of verifying again.",
        )
