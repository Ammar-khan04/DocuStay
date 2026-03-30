"""Tracks invitation codes a guest has not yet signed; shown as 'pending invites' on guest dashboard."""
from sqlalchemy import Column, Integer, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship
from app.database import Base


class GuestPendingInvite(Base):
    __tablename__ = "guest_pending_invites"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    invitation_id = Column(Integer, ForeignKey("invitations.id"), nullable=False)

    __table_args__ = (UniqueConstraint("user_id", "invitation_id", name="uq_guest_pending_invite_user_invitation"),)

    user = relationship("User", backref="pending_invites")
    invitation = relationship("Invitation", backref="pending_for_guests")
