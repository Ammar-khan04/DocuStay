"""Module C: Stay creation and storage."""
from sqlalchemy import Column, Integer, String, Date, ForeignKey, DateTime, Enum as SQLEnum
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base
from app.models.guest import PurposeOfStay, RelationshipToOwner


class Stay(Base):
    __tablename__ = "stays"

    id = Column(Integer, primary_key=True, index=True)
    guest_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    property_id = Column(Integer, ForeignKey("properties.id"), nullable=False)
    unit_id = Column(Integer, ForeignKey("units.id"), nullable=True, index=True)
    invitation_id = Column(Integer, ForeignKey("invitations.id"), nullable=True, index=True)  # links to invite token (invitation_code)
    invited_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)  # owner or tenant who invited

    stay_start_date = Column(Date, nullable=False)
    stay_end_date = Column(Date, nullable=False)
    intended_stay_duration_days = Column(Integer, nullable=False)  # derived

    purpose_of_stay = Column(SQLEnum(PurposeOfStay), nullable=False)
    relationship_to_owner = Column(SQLEnum(RelationshipToOwner), nullable=False)
    region_code = Column(String(20), nullable=False)

    # Kill switch: when set, guest must vacate within 12 hours (vacate_by = revoked_at + 12h)
    revoked_at = Column(DateTime(timezone=True), nullable=True)

    # When set, the owner has released the property's USAT token to this stay; only then does the guest see the token
    usat_token_released_at = Column(DateTime(timezone=True), nullable=True)

    # Guest actions: when set, stay is view-only (no Checkout/Cancel stay buttons)
    checked_in_at = Column(DateTime(timezone=True), nullable=True)  # when guest clicks Check in; occupancy/DMS apply only after this
    checked_out_at = Column(DateTime(timezone=True), nullable=True)
    cancelled_at = Column(DateTime(timezone=True), nullable=True)

    # Dead Man's Switch (copied from invitation when stay is created)
    dead_mans_switch_enabled = Column(Integer, nullable=False, default=0)
    dead_mans_switch_alert_email = Column(Integer, nullable=False, default=1)
    dead_mans_switch_alert_sms = Column(Integer, nullable=False, default=0)
    dead_mans_switch_alert_dashboard = Column(Integer, nullable=False, default=1)
    dead_mans_switch_alert_phone = Column(Integer, nullable=False, default=0)
    dead_mans_switch_triggered_at = Column(DateTime(timezone=True), nullable=True)

    # Confirmation flow: when DMS prompts, owner must select Unit Vacated | Lease Renewed | Holdover before deadline
    occupancy_confirmation_response = Column(String(32), nullable=True)  # vacated | renewed | holdover
    occupancy_confirmation_responded_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
