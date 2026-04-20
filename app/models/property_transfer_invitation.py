"""Owner-to-owner property transfer: invitee accepts via link; property.owner_profile_id moves to their OwnerProfile."""
from sqlalchemy import Column, Integer, String, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base

PROPERTY_TRANSFER_INVITE_EXPIRE_DAYS = 7


class PropertyTransferInvitation(Base):
    __tablename__ = "property_transfer_invitations"

    id = Column(Integer, primary_key=True, index=True)
    token = Column(String(64), unique=True, nullable=False, index=True)
    property_id = Column(Integer, ForeignKey("properties.id"), nullable=False, index=True)
    from_user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    email = Column(String(255), nullable=False, index=True)
    status = Column(String(20), nullable=False, default="pending")  # pending, accepted, expired, cancelled
    expires_at = Column(DateTime(timezone=True), nullable=False)
    accepted_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    property_ref = relationship("Property", backref="property_transfer_invitations")
    from_user = relationship("User", foreign_keys=[from_user_id])
