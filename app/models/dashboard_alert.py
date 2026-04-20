"""In-platform dashboard alerts. Required for all status changes (nearing expiration, renewed, revoked, expired).
Notification methods (email, SMS) are optional and customizable; dashboard alerts are always created."""
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Boolean
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func
from app.database import Base


class DashboardAlert(Base):
    __tablename__ = "dashboard_alerts"

    id = Column(Integer, primary_key=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Recipient (who sees this alert in their dashboard)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)

    # Alert type for filtering/display: nearing_expiration, legal_warning, overstay, dms_48h, dms_urgent,
    # dms_executed, shield_on, shield_off, revoked, renewed, vacated, holdover, expired, invitation_expired,
    # vacant_monitoring, removal_initiated, etc.
    alert_type = Column(String(64), nullable=False, index=True)

    title = Column(String(255), nullable=False)
    message = Column(Text, nullable=False)
    # info | warning | urgent
    severity = Column(String(16), nullable=False, default="info", index=True)

    # Optional links to entity (for deep links / context)
    property_id = Column(Integer, ForeignKey("properties.id", ondelete="SET NULL"), nullable=True, index=True)
    stay_id = Column(Integer, ForeignKey("stays.id", ondelete="SET NULL"), nullable=True, index=True)
    invitation_id = Column(Integer, ForeignKey("invitations.id", ondelete="SET NULL"), nullable=True, index=True)

    read_at = Column(DateTime(timezone=True), nullable=True)
    meta = Column(JSONB, nullable=True)
