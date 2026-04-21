"""Single-source state resolver for invitations, assignments, and stays.

Goal: eliminate per-screen ad-hoc status logic. Backend computes:
- invite_status
- assignment_status
- stay_status

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
) -> ResolvedState:
    """Resolve state for owner-facing tenant lease rows (tenant assignment + tenant invite)."""
    from app.services.tenant_lease_window import resolve_tenant_lease_assignment_status

    # Tenant leases are not modeled as Stays; keep stay_status as none for this resolver.
    inv_status = resolve_invite_status(tenant_invitation)
    asg_status = cast(
        AssignmentStatus,
        resolve_tenant_lease_assignment_status(
            tenant_assignment,
            tenant_invitation,
            today=date.today(),
        ),
    )
    return ResolvedState(invite_status=inv_status, assignment_status=asg_status, stay_status="none")


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

