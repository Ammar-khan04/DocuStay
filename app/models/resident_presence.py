"""Resident presence status (present/away) per user per unit."""
import enum
from sqlalchemy import Column, Integer, ForeignKey, Enum as SQLEnum, DateTime, Date, Boolean, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base


class PresenceStatus(str, enum.Enum):
    present = "present"
    away = "away"


class ResidentPresence(Base):
    __tablename__ = "resident_presences"
    __table_args__ = (UniqueConstraint("user_id", "unit_id", name="uq_resident_presence_user_unit"),)

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    unit_id = Column(Integer, ForeignKey("units.id"), nullable=False, index=True)
    status = Column(SQLEnum(PresenceStatus), nullable=False, default=PresenceStatus.present)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    away_started_at = Column(DateTime(timezone=True), nullable=True)
    away_ended_at = Column(DateTime(timezone=True), nullable=True)
    away_until = Column(Date, nullable=True)  # Optional planned return date
    guests_authorized_during_away = Column(Boolean, nullable=False, default=False)

    user = relationship("User", backref="resident_presences")
    unit = relationship("Unit", backref="resident_presences")
