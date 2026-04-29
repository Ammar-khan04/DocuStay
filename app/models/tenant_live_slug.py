"""Tenant-scoped public live slug for a property (short-lived)."""
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.sql import func

from app.database import Base


class TenantLiveSlug(Base):
    __tablename__ = "tenant_live_slugs"

    id = Column(Integer, primary_key=True, index=True)
    property_id = Column(Integer, ForeignKey("properties.id"), nullable=False, index=True)
    tenant_user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    slug = Column(String(64), unique=True, nullable=False, index=True)
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
