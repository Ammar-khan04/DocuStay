"""Unit model for multi-unit properties. Single-unit properties may have 0 or 1 Unit row."""
from sqlalchemy import Column, Integer, String, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base
from app.models.owner import OccupancyStatus


class Unit(Base):
    __tablename__ = "units"

    id = Column(Integer, primary_key=True, index=True)
    property_id = Column(Integer, ForeignKey("properties.id"), nullable=False, index=True)
    unit_label = Column(String(32), nullable=False)  # e.g. "101", "A", "1"
    occupancy_status = Column(String(32), nullable=False, default=OccupancyStatus.vacant.value)
    # True when owner lives in this unit (primary residence); at most one unit per property
    is_primary_residence = Column(Integer, nullable=False, default=0)  # 0 | 1 (SQLite-friendly)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    property_ref = relationship("Property", backref="units")
