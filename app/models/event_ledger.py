"""System-wide event ledger. Append-only, immutable.
Every meaningful platform action is recorded here.
All logs, audit trails, and activity views read from this ledger."""
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func
from app.database import Base


class EventLedger(Base):
    __tablename__ = "event_ledger"

    id = Column(Integer, primary_key=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Who did it (nullable for system/background events)
    actor_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)

    # What happened
    action_type = Column(String(64), nullable=False, index=True)
    target_object_type = Column(String(64), nullable=True, index=True)
    target_object_id = Column(Integer, nullable=True, index=True)

    # For filtering (property/unit scoped views)
    property_id = Column(Integer, ForeignKey("properties.id", ondelete="SET NULL"), nullable=True, index=True)
    unit_id = Column(Integer, ForeignKey("units.id", ondelete="SET NULL"), nullable=True, index=True)
    stay_id = Column(Integer, ForeignKey("stays.id", ondelete="SET NULL"), nullable=True, index=True)
    invitation_id = Column(Integer, ForeignKey("invitations.id", ondelete="SET NULL"), nullable=True, index=True)

    # State changes for audit
    previous_value = Column(JSONB, nullable=True)
    new_value = Column(JSONB, nullable=True)
    meta = Column(JSONB, nullable=True)  # extra event data (guest_email, stay dates, etc.)

    # Request context
    ip_address = Column(String(64), nullable=True)
    user_agent = Column(String(500), nullable=True)
