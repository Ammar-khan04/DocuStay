"""Property-scoped invitation pipeline counts for dashboards and live page.

Counts are independent of unit occupancy — they describe invitation rows, aligned with product SOT:

- **Guest** (and non–unit-tenant) invites: ``resolve_unified_invitation_lifecycle`` on the row.
- **Property tenant lease** invites (kinds with unit lease semantics): ``resolve_tenant_lease_lifecycle``,
  pairing the invite with ``TenantAssignment`` when found so **active** means the same thing as
  ``resolve_tenant_lease_assignment_status`` (in lease window *and* accepted), not invitation dates alone.

**Ended** aggregates revoked, owner-cancelled, and time-expired terminal outcomes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy.orm import Session

from app.models.invitation import Invitation
from app.services.invitation_kinds import is_property_invited_tenant_signup_kind
from app.services.state_resolver import resolve_tenant_lease_lifecycle, resolve_unified_invitation_lifecycle
from app.services.tenant_lease_window import find_tenant_assignment_for_invitation_summary

if TYPE_CHECKING:
    from app.models.user import User


def resolve_invitation_pipeline_lifecycle(inv: Invitation, db: Session, *, today: date | None = None) -> str:
    """Unified lifecycle string for one invitation row (tenant lease uses assignment + invite rules)."""
    today = today or date.today()
    if is_property_invited_tenant_signup_kind(getattr(inv, "invitation_kind", None)) and getattr(
        inv, "unit_id", None
    ) is not None:
        ta = find_tenant_assignment_for_invitation_summary(db, inv)
        return resolve_tenant_lease_lifecycle(
            tenant_assignment=ta,
            tenant_invitation=inv,
            today=today,
            db=db,
        )
    return resolve_unified_invitation_lifecycle(inv, today=today, db=db)


@dataclass(frozen=True)
class InvitationPipelineCounts:
    pending: int
    accepted: int
    active: int
    cancelled: int


def summarize_invitations_pipeline(invitations: list[Invitation], db: Session) -> InvitationPipelineCounts:
    today = date.today()
    pending = accepted = active = cancelled = 0
    for inv in invitations:
        lc = resolve_invitation_pipeline_lifecycle(inv, db, today=today)
        if lc in ("PENDING_STAGED", "PENDING_INVITED"):
            pending += 1
        elif lc == "ACCEPTED":
            accepted += 1
        elif lc == "ACTIVE":
            active += 1
        else:
            cancelled += 1
    return InvitationPipelineCounts(
        pending=pending, accepted=accepted, active=active, cancelled=cancelled
    )


def invitation_counts_dict(invitations: list[Invitation], db: Session) -> dict[str, int]:
    s = summarize_invitations_pipeline(invitations, db)
    return {
        "invitation_pending_count": s.pending,
        "invitation_accepted_count": s.accepted,
        "invitation_active_count": s.active,
        "invitation_cancelled_count": s.cancelled,
    }


def filter_invitations_for_live_property_evidence(
    db: Session,
    *,
    property_id: int,
    viewer: "User | None",
) -> list[Invitation]:
    """Same visibility rules as invitation rows on GET /public/live/{slug} (before the 50-row cap)."""
    from app.models.user import UserRole

    invs = db.query(Invitation).filter(Invitation.property_id == property_id).all()
    if viewer is not None and getattr(viewer, "role", None) == UserRole.tenant:
        invs = [
            inv
            for inv in invs
            if (getattr(inv, "invitation_kind", None) or "guest").strip().lower() != "guest"
            or getattr(inv, "invited_by_user_id", None) == viewer.id
        ]
    if viewer is not None and getattr(viewer, "role", None) == UserRole.guest:
        from app.services.invitation_kinds import is_property_invited_tenant_signup_kind

        invs = [inv for inv in invs if not is_property_invited_tenant_signup_kind(getattr(inv, "invitation_kind", None))]
    return invs
