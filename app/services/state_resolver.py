"""Single-source state resolver for invitations, assignments, and stays.

Goal: eliminate per-screen ad-hoc status logic. Backend computes:
- invite_status
- assignment_status
- stay_status

Dashboard guest rows should use ``resolve_guest_stay_state_fields`` (lifecycle + stay + invite)
instead of re-assembling resolver calls elsewhere.

Tenant lease dashboard rows should use ``resolve_tenant_lease_state_fields``.

Public live / verify should use ``resolve_public_*``, ``resolve_verify_*``, and
``resolve_live_property_authorization_state`` — routers must not re-implement stay or lease status chains.

UI should render from these fields, not re-derive them.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal, cast

from sqlalchemy.orm import Session

from app.models.invitation import Invitation
from app.models.stay import Stay
from app.models.tenant_assignment import TenantAssignment


InviteStatus = Literal["pending", "accepted", "cancelled", "revoked", "expired", "unknown"]
AssignmentStatus = Literal["none", "pending", "accepted", "active", "expired"]
StayStatus = Literal["none", "upcoming", "checked_in", "checked_out", "cancelled", "revoked", "ended"]
UnifiedLifecycleStatus = Literal[
    "PENDING_STAGED",
    "PENDING_INVITED",
    "ACCEPTED",
    "ACTIVE",
    "EXPIRED",
    "OWNER_RESIDENT",
    "CANCELLED",
]
DisplayLifecycleStatus = Literal["pending", "accepted", "active", "expired", "cancelled"]


@dataclass(frozen=True)
class ResolvedState:
    invite_status: InviteStatus
    assignment_status: AssignmentStatus
    stay_status: StayStatus


def resolve_invite_status(inv: Invitation | None) -> InviteStatus:
    if inv is None:
        return "unknown"
    raw = (getattr(inv, "status", None) or "").strip().lower()
    tok = (getattr(inv, "token_state", None) or "").strip().upper()
    if tok == "REVOKED":
        return "revoked"
    if tok == "CANCELLED" or raw == "cancelled":
        return "cancelled"
    if tok == "EXPIRED" or raw == "expired":
        return "expired"
    if raw == "accepted" or tok == "BURNED":
        return "accepted"
    if raw in ("pending", "ongoing"):
        return "pending"
    return "unknown"


def resolve_unified_invitation_lifecycle(
    inv: Invitation | None,
    *,
    today: date | None = None,
    db: Session | None = None,
) -> UnifiedLifecycleStatus:
    """Single lifecycle resolver for invitation-backed authorization.

    Rules:
    - ACTIVE is always runtime-derived from acceptance + lease window.
    - PENDING_STAGED is never treated as accepted/active.
    - OWNER_RESIDENT is not inferred from invitation rows.
    - CSV bulk-upload tenant invites (ledger InvitationCreatedCSV) use PENDING_STAGED until accepted,
      even when invited_by_user_id is set.
    """
    if inv is None:
        return "PENDING_STAGED"
    today = today or date.today()
    raw = (getattr(inv, "status", None) or "").strip().lower()
    tok = (getattr(inv, "token_state", None) or "").strip().upper()
    invited_by_user_id = getattr(inv, "invited_by_user_id", None)
    start = getattr(inv, "stay_start_date", None)
    end = getattr(inv, "stay_end_date", None)

    if tok in ("REVOKED", "CANCELLED") or raw == "cancelled":
        return "CANCELLED"
    if tok == "EXPIRED" or raw == "expired":
        return "EXPIRED"

    accepted = raw == "accepted" or tok == "BURNED"
    if accepted:
        if end is not None and end < today:
            return "EXPIRED"
        in_window = start is not None and start <= today and (end is None or today <= end)
        if in_window:
            return "ACTIVE"
        return "ACCEPTED"

    # STAGED/pending: bulk CSV tenant invites stay PENDING_STAGED until accept; otherwise system vs user-invited.
    if tok == "STAGED" and raw in ("", "pending", "ongoing"):
        if db is not None:
            from app.services.invitation_kinds import is_property_invited_tenant_signup_kind
            from app.services.event_ledger import invitation_has_csv_bulk_creation_record

            if is_property_invited_tenant_signup_kind(
                getattr(inv, "invitation_kind", None)
            ) and invitation_has_csv_bulk_creation_record(db, getattr(inv, "id", None)):
                return "PENDING_STAGED"
        return "PENDING_STAGED" if invited_by_user_id is None else "PENDING_INVITED"

    return "PENDING_INVITED"


def resolve_invitation_display_status(
    inv: Invitation | None,
    *,
    today: date | None = None,
    force_expired: bool = False,
    has_live_stay: bool = False,
    has_terminal_stays_only: bool = False,
    db: Session | None = None,
) -> DisplayLifecycleStatus:
    """Compatibility mapping for API/UI status fields while using unified lifecycle rules."""
    if force_expired:
        return "expired"
    lifecycle = resolve_unified_invitation_lifecycle(inv, today=today, db=db)
    if lifecycle == "CANCELLED":
        return "cancelled"
    if lifecycle == "EXPIRED":
        return "expired"
    if has_live_stay:
        return "active"
    if has_terminal_stays_only and lifecycle in ("ACCEPTED", "ACTIVE"):
        return "expired"
    if lifecycle == "ACTIVE":
        return "active"
    if lifecycle == "ACCEPTED":
        return "accepted"
    return "pending"


def resolve_stay_status(stay: Stay | None, *, today: date | None = None) -> StayStatus:
    if stay is None:
        return "none"
    today = today or date.today()
    if getattr(stay, "cancelled_at", None) is not None:
        return "cancelled"
    if getattr(stay, "revoked_at", None) is not None:
        return "revoked"
    if getattr(stay, "checked_out_at", None) is not None:
        return "checked_out"
    if getattr(stay, "checked_in_at", None) is not None:
        return "checked_in"
    # not checked in yet
    start = getattr(stay, "stay_start_date", None)
    end = getattr(stay, "stay_end_date", None)
    if start is not None and start > today:
        return "upcoming"
    if end is not None and end < today:
        return "ended"
    return "upcoming"


def resolve_tenant_state(
    db: Session,
    *,
    tenant_assignment: TenantAssignment | None,
    tenant_invitation: Invitation | None,
    today: date | None = None,
) -> ResolvedState:
    """Resolve state for owner-facing tenant lease rows (tenant assignment + tenant invite)."""
    from app.services.tenant_lease_window import resolve_tenant_lease_assignment_status

    eff = today or date.today()
    # Tenant leases are not modeled as Stays; keep stay_status as none for this resolver.
    inv_status = resolve_invite_status(tenant_invitation)
    asg_status = cast(
        AssignmentStatus,
        resolve_tenant_lease_assignment_status(
            tenant_assignment,
            tenant_invitation,
            today=eff,
        ),
    )
    return ResolvedState(invite_status=inv_status, assignment_status=asg_status, stay_status="none")


def resolve_tenant_lease_state_fields(
    db: Session,
    *,
    tenant_assignment: TenantAssignment | None,
    tenant_invitation: Invitation | None,
    today: date | None = None,
) -> dict[str, str]:
    """Single bundle for tenant lease dashboard rows (same ``today`` for assignment + lifecycle)."""
    eff = today or date.today()
    rs = resolve_tenant_state(
        db,
        tenant_assignment=tenant_assignment,
        tenant_invitation=tenant_invitation,
        today=eff,
    )
    lc = resolve_tenant_lease_lifecycle(
        tenant_assignment=tenant_assignment,
        tenant_invitation=tenant_invitation,
        today=eff,
        db=db,
    )
    return {
        "lifecycle_state": lc,
        "invite_status": rs.invite_status,
        "assignment_status": rs.assignment_status,
        "stay_status": rs.stay_status,
    }


def public_label_for_tenant_lease_assignment_status(st: str) -> str:
    """Human label for assignment status (public live / verify copy)."""
    return {
        "none": "No assignment on file",
        "pending": "Pending invitation",
        "accepted": "Accepted — outside active lease window today",
        "active": "Active lease",
        "expired": "Expired or ended",
    }.get(st, st.replace("_", " ").title())


def resolve_public_tenant_assignment_row_label(db: Session, ta: TenantAssignment, today: date) -> str:
    """Public pages: one label string from assignment + invite (via ``resolve_tenant_lease_assignment_status``)."""
    from app.models.user import User
    from app.services.tenant_lease_window import find_invitation_matching_tenant_assignment, resolve_tenant_lease_assignment_status

    u = db.query(User).filter(User.id == ta.user_id).first() if ta.user_id else None
    em = (u.email or "").strip().lower() if u else None
    inv = find_invitation_matching_tenant_assignment(db, ta, user_email_lower=em)
    st = resolve_tenant_lease_assignment_status(ta, inv, today=today)
    return public_label_for_tenant_lease_assignment_status(st)


def resolve_public_tenant_stay_invitation_row_label(
    inv: Invitation | None,
    *,
    today: date,
    db: Session | None = None,
) -> str:
    """Public pages: label when a guest stay row is tied to an invitation (``has_live_stay=True``)."""
    disp = resolve_invitation_display_status(inv, today=today, has_live_stay=True, db=db)
    return {
        "pending": "Pending invitation",
        "accepted": "Accepted (invitation)",
        "active": "Active (checked-in tenant stay)",
        "expired": "Expired",
        "cancelled": "Cancelled or revoked",
    }.get(disp, disp.replace("_", " ").title())


_STAY_STATUS_TO_VERIFY_PAGE: dict[str, str] = {
    "cancelled": "CANCELLED",
    "revoked": "REVOKED",
    "checked_out": "COMPLETED",
    "checked_in": "ACTIVE",
    "upcoming": "PENDING",
    "ended": "EXPIRED",
    "none": "PENDING",
}


_INV_DISPLAY_TO_VERIFY_PAGE: dict[str, str] = {
    "cancelled": "CANCELLED",
    "expired": "EXPIRED",
    "active": "ACTIVE",
    "accepted": "ACCEPTED",
    "pending": "PENDING",
}


def resolve_verify_primary_guest_stay_status(
    inv: Invitation,
    stay: Stay | None,
    *,
    today: date,
    db: Session,
) -> str:
    """Verify portal: top-level ``status`` string (invitation-only or physical stay), via resolver stay/invite rules."""
    if stay is None:
        disp = resolve_invitation_display_status(inv, today=today, has_live_stay=False, db=db)
        return _INV_DISPLAY_TO_VERIFY_PAGE.get(disp, "PENDING")
    sst = resolve_stay_status(stay, today=today)
    return _STAY_STATUS_TO_VERIFY_PAGE.get(sst, "PENDING")


def resolve_verify_guest_authorization_history_status(stay: Stay, *, today: date) -> str:
    """Verify portal: per-stay row in authorization history (same ordering as ``resolve_stay_status`` semantics)."""
    sst = resolve_stay_status(stay, today=today)
    return _STAY_STATUS_TO_VERIFY_PAGE.get(sst, "PENDING")


def resolve_live_property_authorization_state(
    *,
    has_current_guest_stays: bool,
    all_current_stays_revoked: bool,
    has_last_ended_stay: bool,
    viewer_is_record_owner_for_property: bool,
) -> str:
    """Public live payload: coarse property guest-authorization banner state."""
    if has_current_guest_stays:
        return "REVOKED" if all_current_stays_revoked else "ACTIVE"
    if has_last_ended_stay:
        return "EXPIRED"
    if viewer_is_record_owner_for_property:
        return "ACTIVE"
    return "NONE"


def resolve_guest_stay_state_fields(
    db: Session,
    *,
    stay: Stay | None,
    invitation: Invitation | None,
    today: date | None = None,
) -> dict[str, str]:
    """Single entry point for dashboard guest rows: lifecycle + stay + invite status (same rules as tenant lease.

    Pass ``today`` from ``X-Client-Calendar-Date`` (clamped) for guest-facing endpoints so ACTIVE/ACCEPTED
    matches the browser calendar; omit for server-default UTC calendar day.
    """
    eff = today or date.today()
    lc = resolve_guest_stay_lifecycle(stay=stay, invitation=invitation, today=eff, db=db)
    inv_st = resolve_invite_status(invitation) if invitation is not None else "unknown"
    stay_st = resolve_stay_status(stay, today=eff) if stay is not None else "none"
    if (
        invitation is not None
        and stay is not None
        and inv_st == "pending"
        and getattr(stay, "invitation_id", None) == invitation.id
        and getattr(stay, "cancelled_at", None) is None
        and getattr(stay, "revoked_at", None) is None
        and getattr(stay, "checked_out_at", None) is None
    ):
        inv_st = "accepted"
    return {
        "lifecycle_state": lc,
        "stay_status": stay_st,
        "invite_status": inv_st,
    }


def resolve_guest_stay_lifecycle(
    *,
    stay: Stay | None,
    invitation: Invitation | None,
    today: date | None = None,
    db: Session | None = None,
) -> UnifiedLifecycleStatus:
    """Owner/manager guest-stay lifecycle: same acceptance + calendar window SOT as tenant lease.

    When a physical Stay exists and is not in a terminal state, calendar + check-in drive
    ACCEPTED/ACTIVE so the dashboard matches reality even if the Invitation row still shows
    pending/ongoing with a STAGED token (e.g. right after signing, before token/status sync).

    Invitation-only rows (no stay yet) still use ``resolve_unified_invitation_lifecycle``.
    Physical stay terminals (cancelled, revoked, checked out) win before invitation rules.
    """
    today = today or date.today()
    if stay is not None:
        if getattr(stay, "cancelled_at", None) is not None:
            return "CANCELLED"
        if getattr(stay, "revoked_at", None) is not None:
            return "CANCELLED"
        if getattr(stay, "checked_out_at", None) is not None:
            return "EXPIRED"
        start = getattr(stay, "stay_start_date", None)
        end = getattr(stay, "stay_end_date", None)
        if getattr(stay, "checked_in_at", None) is not None:
            if end is not None and end < today:
                return "EXPIRED"
            in_window = start is not None and start <= today and (end is None or today <= end)
            if in_window:
                return "ACTIVE"
            return "ACCEPTED"
        if end is not None and end < today:
            return "EXPIRED"
        in_window = start is not None and start <= today and (end is None or today <= end)
        if in_window:
            return "ACTIVE"
        if start is not None and start > today:
            return "ACCEPTED"
        return "EXPIRED"
    if invitation is not None:
        return resolve_unified_invitation_lifecycle(invitation, today=today, db=db)
    return "PENDING_STAGED"


def resolve_tenant_lease_lifecycle(
    *,
    tenant_assignment: TenantAssignment | None,
    tenant_invitation: Invitation | None,
    today: date | None = None,
    db: Session | None = None,
) -> UnifiedLifecycleStatus:
    """Unified tenant lease lifecycle for dashboard/API consumers.

    When a TenantAssignment exists, its calendar + acceptance rules (same as
    resolve_tenant_lease_assignment_status) are authoritative. Otherwise we
    fall back to invitation-only lifecycle (CSV / pending invite rows).
    """
    today = today or date.today()
    if tenant_assignment is not None:
        from app.services.tenant_lease_window import resolve_tenant_lease_assignment_status

        asg = resolve_tenant_lease_assignment_status(
            tenant_assignment,
            tenant_invitation,
            today=today,
        )
        if asg == "active":
            return "ACTIVE"
        if asg == "accepted":
            return "ACCEPTED"
        if asg == "expired":
            return "EXPIRED"
        if asg == "pending":
            return "PENDING_INVITED"
        # asg == "none" with a row present should not happen; treat as invitation-only edge.
        if tenant_invitation is not None:
            return resolve_unified_invitation_lifecycle(tenant_invitation, today=today, db=db)
        return "PENDING_STAGED"

    if tenant_invitation is not None:
        return resolve_unified_invitation_lifecycle(tenant_invitation, today=today, db=db)
    return "PENDING_STAGED"

