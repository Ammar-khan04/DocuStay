"""Property Manager invitation: owner invites a manager by email; manager signs up via token."""
from datetime import datetime, timezone, timedelta
from sqlalchemy import Column, Integer, String, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base

MANAGER_INVITE_EXPIRE_DAYS = 3


class ManagerInvitation(Base):
    __tablename__ = "manager_invitations"

    id = Column(Integer, primary_key=True, index=True)
    token = Column(String(64), unique=True, nullable=False, index=True)
    property_id = Column(Integer, ForeignKey("properties.id"), nullable=False)
    invited_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    email = Column(String(255), nullable=False, index=True)
    status = Column(String(20), nullable=False, default="pending")  # pending, accepted, expired, cancelled
    expires_at = Column(DateTime(timezone=True), nullable=False)
    accepted_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    property_ref = relationship("Property", backref="manager_invitations")
    invited_by = relationship("User", foreign_keys=[invited_by_user_id])
