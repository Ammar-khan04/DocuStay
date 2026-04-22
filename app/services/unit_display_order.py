"""Stable ordering for Unit rows on a property (APIs, occupancy helpers, live views).

Rule: owner primary residence first, then unit label (case-insensitive), then id.
"""

from __future__ import annotations

from sqlalchemy import func
from sqlalchemy.orm import Query, Session

from app.models.unit import Unit


def order_units_for_property_display(q: Query) -> Query:
    """Apply stable logical sort for units belonging to one property."""
    return q.order_by(
        Unit.is_primary_residence.desc(),
        func.lower(Unit.unit_label).asc(),
        Unit.id.asc(),
    )


def query_units_for_property_ordered(db: Session, property_id: int) -> Query:
    return order_units_for_property_display(db.query(Unit).filter(Unit.property_id == property_id))


def query_units_for_properties_ordered(db: Session, property_ids: list[int]) -> Query:
    """Multiple properties: sort by property_id, then same per-property ordering."""
    if not property_ids:
        return db.query(Unit).filter(Unit.id == -1)
    return db.query(Unit).filter(Unit.property_id.in_(property_ids)).order_by(
        Unit.property_id.asc(),
        Unit.is_primary_residence.desc(),
        func.lower(Unit.unit_label).asc(),
        Unit.id.asc(),
    )
