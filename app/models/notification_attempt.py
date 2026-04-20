"""Log of notification delivery attempts (email, SMS, etc.) for alerts. Supports repeat attempts and auditing."""
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Boolean
from sqlalchemy.sql import func
from app.database import Base


class NotificationAttempt(Base):
    __tablename__ = "notification_attempts"

    id = Column(Integer, primary_key=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    dashboard_alert_id = Column(
        Integer, ForeignKey("dashboard_alerts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # email | sms | in_app (in_app is created when alert is created; email/sms when we send off-platform)
    channel = Column(String(32), nullable=False, index=True)
    success = Column(Boolean, nullable=False)
    error_message = Column(Text, nullable=True)
