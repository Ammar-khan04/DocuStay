"""
Event ledger rows for public live / verify property timelines.

GET /public/live/{slug} and verify merge ledger rows tied to the property (property_id,
stay, invitation, or unit on the property).

By default, guest-stay lifecycle and guest invite/authorization rows are excluded for
public / owner-style evidence. Presence changes (Present/Away) are included so the full
chain of events is visible on the audit timeline and live link.
Stay-end reminder events may appear; display text scrubs the substring ``dms``.
The live router passes ``exclude_guest_stay_actions=False`` when the Bearer viewer is an
assigned tenant on that property so they still see guest-stay notifications on the timeline.
"""
from __future__ import annotations

from sqlalchemy import and_, desc, or_
from sqlalchemy.orm import Session

from app.models.event_ledger import EventLedger
from app.models.invitation import Invitation
from app.models.stay import Stay
from app.models.unit import Unit
from app.services import event_ledger as el


# Actions excluded from merged public property ledgers (live + verify).
# Presence actions (AwayActivated, AwayEnded, PresenceStatusChanged) are NOT excluded —
# they must appear on the audit timeline so the full chain of events is visible.
_LIVE_PUBLIC_LEDGER_EXCLUDED_ACTIONS: frozenset[str] = frozenset(
    {
        el.ACTION_GUEST_INVITE_CREATED,
        el.ACTION_GUEST_INVITE_ACCEPTED,
        el.ACTION_GUEST_INVITE_REVOKED,
        el.ACTION_GUEST_INVITE_CANCELLED,
        el.ACTION_GUEST_CHECK_IN,
        el.ACTION_GUEST_CHECK_OUT,
        el.ACTION_STAY_CANCELLED,
        el.ACTION_STAY_REVOKED,
        el.ACTION_STAY_CREATED,
        el.ACTION_OVERSTAY_OCCURRED,
        el.ACTION_GUEST_AUTHORIZATION_CREATED,
        el.ACTION_GUEST_AUTHORIZATION_ACTIVE,
        el.ACTION_GUEST_AUTHORIZATION_REVOKED,
        el.ACTION_GUEST_AUTHORIZATION_EXPIRED,
        el.ACTION_GUEST_STAY_APPROACHING_END,
        el.ACTION_TENANT_GUEST_JURISDICTION_THRESHOLD_APPROACHING,
        el.ACTION_GUEST_EXTENSION_REQUESTED,
        el.ACTION_GUEST_EXTENSION_APPROVED,
        el.ACTION_GUEST_EXTENSION_DECLINED,
    }
)


def merged_public_property_ledger_rows(
    db: Session,
    property_id: int,
    *,
    limit: int = 500,
    exclude_guest_stay_actions: bool = True,
) -> list[EventLedger]:
    """Newest-first ledger rows for this property.

    When ``exclude_guest_stay_actions`` is true (default), guest-stay lanes are omitted for
    property-level / verify timelines. Set false for assigned-tenant live viewers who should
    see guest-stay notifications. Presence actions are always included so the audit timeline
    reflects all status and presence changes.
    """
    stay_ids = [r[0] for r in db.query(Stay.id).filter(Stay.property_id == property_id).all()]
    inv_ids = [r[0] for r in db.query(Invitation.id).filter(Invitation.property_id == property_id).all()]
    unit_ids = [r[0] for r in db.query(Unit.id).filter(Unit.property_id == property_id).all()]

    conditions: list = [EventLedger.property_id == property_id]
    if stay_ids:
        conditions.append(EventLedger.stay_id.in_(stay_ids))
    if inv_ids:
        conditions.append(EventLedger.invitation_id.in_(inv_ids))
    if unit_ids:
        conditions.append(EventLedger.unit_id.in_(unit_ids))

    scope = or_(*conditions)
    if not exclude_guest_stay_actions:
        return (
            db.query(EventLedger)
            .filter(scope)
            .order_by(desc(EventLedger.created_at))
            .limit(limit)
            .all()
        )

    action_ok = or_(
        EventLedger.action_type.is_(None),
        ~EventLedger.action_type.in_(_LIVE_PUBLIC_LEDGER_EXCLUDED_ACTIONS),
    )

    return (
        db.query(EventLedger)
        .filter(and_(scope, action_ok))
        .order_by(desc(EventLedger.created_at))
        .limit(limit)
        .all()
    )
