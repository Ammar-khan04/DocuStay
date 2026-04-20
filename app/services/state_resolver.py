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

