"""Guest requests a longer stay (tenant-lane); tenant approves or declines in dashboard."""
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey
from sqlalchemy.sql import func
from app.database import Base


class GuestExtensionRequest(Base):
    __tablename__ = "guest_extension_requests"

    id = Column(Integer, primary_key=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    responded_at = Column(DateTime(timezone=True), nullable=True)

    stay_id = Column(Integer, ForeignKey("stays.id", ondelete="CASCADE"), nullable=False, index=True)
    property_id = Column(Integer, ForeignKey("properties.id", ondelete="CASCADE"), nullable=False, index=True)
    guest_user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    tenant_user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)

    # Optional note from guest when requesting
    message = Column(Text, nullable=True)
    # pending | approved | declined
    status = Column(String(24), nullable=False, default="pending", index=True)
    # Optional note from tenant (e.g. decline reason)
    tenant_note = Column(Text, nullable=True)
