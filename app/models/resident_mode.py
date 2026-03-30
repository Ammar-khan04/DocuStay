"""ResidentMode: links Owner or Property Manager to a unit for Personal Mode (resident-like interactions)."""
import enum
from sqlalchemy import Column, Integer, ForeignKey, Enum as SQLEnum, DateTime
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base


class ResidentModeType(str, enum.Enum):
    owner_personal = "owner_personal"
    manager_personal = "manager_personal"


class ResidentMode(Base):
    __tablename__ = "resident_modes"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    unit_id = Column(Integer, ForeignKey("units.id"), nullable=False, index=True)
    mode = Column(SQLEnum(ResidentModeType), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", backref="resident_modes")
    unit = relationship("Unit", backref="resident_modes")
