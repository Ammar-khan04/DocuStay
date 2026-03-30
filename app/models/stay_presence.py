"""Guest presence (present/away) for an ongoing stay. One row per stay; guest can set status when checked in."""
import enum
from sqlalchemy import Column, Integer, ForeignKey, Enum as SQLEnum, DateTime, Boolean, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base
from app.models.resident_presence import PresenceStatus


class StayPresence(Base):
    __tablename__ = "stay_presences"
    __table_args__ = (UniqueConstraint("stay_id", name="uq_stay_presence_stay"),)

    id = Column(Integer, primary_key=True, index=True)
    stay_id = Column(Integer, ForeignKey("stays.id", ondelete="CASCADE"), nullable=False, index=True)
    status = Column(SQLEnum(PresenceStatus), nullable=False, default=PresenceStatus.present)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    away_started_at = Column(DateTime(timezone=True), nullable=True)
    away_ended_at = Column(DateTime(timezone=True), nullable=True)
    guests_authorized_during_away = Column(Boolean, nullable=False, default=False)

    stay = relationship("Stay", backref="stay_presence")


class PresenceAwayPeriod(Base):
    """Completed away period: creates a full timeline of intended occupancy (away start + end)."""
    __tablename__ = "presence_away_periods"

    id = Column(Integer, primary_key=True, index=True)
    resident_presence_id = Column(Integer, ForeignKey("resident_presences.id", ondelete="CASCADE"), nullable=True, index=True)
    stay_id = Column(Integer, ForeignKey("stays.id", ondelete="CASCADE"), nullable=True, index=True)
    away_started_at = Column(DateTime(timezone=True), nullable=False)
    away_ended_at = Column(DateTime(timezone=True), nullable=False)
    guests_authorized_during_away = Column(Boolean, nullable=False, default=False)

    resident_presence = relationship("ResidentPresence")
    stay = relationship("Stay", backref="away_periods")
