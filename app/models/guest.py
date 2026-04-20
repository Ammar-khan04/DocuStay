"""Module B2: Guest onboarding."""
from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, Enum as SQLEnum, DateTime
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base
import enum


class PurposeOfStay(str, enum.Enum):
    business = "business"
    personal = "personal"
    travel = "travel"
    other = "other"


class RelationshipToOwner(str, enum.Enum):
    friend = "friend"
    family = "family"
    employee = "employee"
    other = "other"


class GuestProfile(Base):
    __tablename__ = "guest_profiles"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), unique=True, nullable=False)

    full_legal_name = Column(String(255), nullable=False)
    permanent_home_address = Column(String(500), nullable=False)
    gps_checkin_acknowledgment = Column(Boolean, default=False)  # Demo: checkbox only

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    user = relationship("User", backref="guest_profile")
