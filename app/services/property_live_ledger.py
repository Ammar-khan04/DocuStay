"""
Event ledger rows for public live / verify property timelines.

GET /public/live/{slug} and verify use one inclusive query: every ledger event tied to
the property (owner, manager, tenant, and guest). Rows match property_id on the event,
or stay/invitation/unit that belongs to the property — no action-type or privacy-lane
filtering so the evidence page shows a complete audit trail.
"""
from __future__ import annotations

from sqlalchemy import desc, or_
from sqlalchemy.orm import Session

from app.models.event_ledger import EventLedger
from app.models.invitation import Invitation
from app.models.stay import Stay
from app.models.unit import Unit


def merged_public_property_ledger_rows(
    db: Session,
    property_id: int,
    *,
    limit: int = 500,
) -> list[EventLedger]:
    """Newest-first ledger rows for this property (full scope for public evidence)."""
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

    return (
        db.query(EventLedger)
        .filter(or_(*conditions))
        .order_by(desc(EventLedger.created_at))
        .limit(limit)
        .all()
    )
