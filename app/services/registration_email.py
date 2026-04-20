"""Registration helpers for normalized email and pending-signup checks.

The ``users`` table enforces ``UniqueConstraint("email", "role")``: the same mailbox may register
once per ``UserRole`` (e.g. same person as guest and as tenant). Callers must disambiguate login,
password reset, and similar flows by role where needed.
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


def enforce_email_available_for_intended_role(
    db: Session,
    email_norm: str,
    intended_role: UserRole,
    *,
    allow_same_role_pending: bool = True,
) -> None:
    """
    Reserved for same-role pending collisions. Cross-role reuse of the same email is allowed
    (enforced only by ``UniqueConstraint(email, role)`` on ``User``).

    If ``allow_same_role_pending`` is False, raises when a non-expired ``PendingRegistration``
    exists for the same email and role.
    """
    if not email_norm or allow_same_role_pending:
        return
    now = datetime.now(timezone.utc)
    for p in pending_registrations_with_normalized_email(db, email_norm):
        if p.role == intended_role and p.expires_at >= now:
            pend_label, _ = _role_labels(intended_role)
            raise HTTPException(
                status_code=400,
                detail=(
                    f"A registration is already in progress for this email as a {pend_label}. "
                    "Complete email verification, wait until the code expires, or use a different email."
                ),
            )


def same_role_already_registered_message(existing_role: UserRole) -> str:
    """Existing account with this email and role — tell them to log in."""
    ex_label, ex_page = _role_labels(existing_role)
    return (
        f"This email is already registered as a {ex_label}. "
        f"Please log in using the {ex_page} login page."
    )


def enforce_no_conflicting_user_before_pending_completion(db: Session, email_norm: str, pending_role: UserRole) -> None:
    """Before creating a User from PendingRegistration: same email + role must not already exist as a User."""
    existing_same_role = (
        db.query(User)
        .filter(func.lower(func.trim(User.email)) == email_norm, User.role == pending_role)
        .first()
    )
    if existing_same_role:
        raise HTTPException(
            status_code=400,
            detail=(
                f"This email is already registered as a {_role_labels(pending_role)[0]}. "
                "Please log in instead of verifying again."
            ),
        )
