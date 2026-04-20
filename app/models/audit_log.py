"""Append-only audit log for immutable audit trail (Rule 803(6)).
No updates or deletes - every record is permanent."""
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func
from app.database import Base


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)

    # Scope: logs visible to owner are filtered by property_id in owner's properties
    # ON DELETE SET NULL so property deletion does not fail; message/meta preserve property name
    property_id = Column(Integer, ForeignKey("properties.id", ondelete="SET NULL"), nullable=True, index=True)
    stay_id = Column(Integer, ForeignKey("stays.id"), nullable=True, index=True)
    invitation_id = Column(Integer, ForeignKey("invitations.id"), nullable=True, index=True)

    # category: status_change | guest_signature | failed_attempt
    category = Column(String(32), nullable=False, index=True)
    title = Column(String(255), nullable=False)
    message = Column(Text, nullable=False)

    # Optional structured data (e.g. old_value, new_value, invitation_code)
    meta = Column(JSONB, nullable=True)

    # Who did it (if applicable)
    actor_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    actor_email = Column(String(255), nullable=True)

    # Request context for legal weight
    ip_address = Column(String(64), nullable=True)
    user_agent = Column(String(500), nullable=True)

    # UTC only - server_default
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
