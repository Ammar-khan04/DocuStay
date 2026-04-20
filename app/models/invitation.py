"""Invitation from owner to guest; links to Stay when guest accepts."""
from sqlalchemy import Column, Integer, String, Date, ForeignKey, Enum as SQLEnum, DateTime
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base
from app.models.guest import PurposeOfStay, RelationshipToOwner


class Invitation(Base):
    __tablename__ = "invitations"

    id = Column(Integer, primary_key=True, index=True)
    invitation_code = Column(String(64), unique=True, nullable=False, index=True)

    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    property_id = Column(Integer, ForeignKey("properties.id"), nullable=False)
    unit_id = Column(Integer, ForeignKey("units.id"), nullable=True, index=True)
    invited_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)  # owner or tenant who created invite
    guest_name = Column(String(255), nullable=True)  # name owner entered when creating invite
    guest_email = Column(String(255), nullable=True)

    stay_start_date = Column(Date, nullable=False)
    stay_end_date = Column(Date, nullable=False)
    purpose_of_stay = Column(SQLEnum(PurposeOfStay), nullable=False)
    relationship_to_owner = Column(SQLEnum(RelationshipToOwner), nullable=False)
    region_code = Column(String(20), nullable=False)

    status = Column(String(20), nullable=False, default="pending")  # pending, accepted, cancelled (legacy rows may contain "ongoing")

    # Invite-as-token state (Invite ID = invitation_code; used as Stay ID for display)
    # STAGED=created, BURNED=guest/tenant accepted+signed, EXPIRED=guest stay ended (guests only; tenants not expired)
    # REVOKED=guest authorization revoked by owner, CANCELLED=tenant self-cancelled (DocuStay does not revoke tenants)
    token_state = Column(String(20), nullable=False, default="STAGED", server_default="STAGED")

    # Whether this invite is for a guest stay or a tenant signup; enforced on verify/signup so links are not interchangeable
    invitation_kind = Column(String(20), nullable=False, default="guest", server_default="guest")

    # Status Confirmation / stay end reminders: auto-protect when stay end passes without owner response
    dead_mans_switch_enabled = Column(Integer, nullable=False, default=0)  # 0 | 1 (SQLite-friendly)
    dead_mans_switch_alert_email = Column(Integer, nullable=False, default=1)
    dead_mans_switch_alert_sms = Column(Integer, nullable=False, default=0)
    dead_mans_switch_alert_dashboard = Column(Integer, nullable=False, default=1)
    dead_mans_switch_alert_phone = Column(Integer, nullable=False, default=0)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    owner = relationship("User", foreign_keys=[owner_id], backref="invitations_sent")
    invited_by = relationship("User", foreign_keys=[invited_by_user_id])
    property_ref = relationship("Property", backref="invitations")
